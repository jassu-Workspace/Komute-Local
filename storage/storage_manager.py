"""Self-Contained Storage Engine for Komüte-Local.

Manages structured image artifact persistence for verification sessions.
Captures raw uploaded originals, privacy-sanitized crops (face and plate),
and post-verification WebP compressed assets.

Architecture Isolation Guarantee:
This module and the 'storage/' folder are completely decoupled.
Deleting this folder or module has zero impact on core backend model execution.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def sanitize_folder_name(name: str) -> str:
    """Sanitize string to strictly prevent directory traversal, separators, or invalid characters."""
    if not name:
        return "unknown"
    clean = re.sub(r"[\/\\]+", "_", str(name).strip())
    clean = re.sub(r"\.{2,}", "_", clean)
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean)
    clean = clean.strip("._")
    if clean in ("", ".", "..", "unknown"):
        return "unknown"
    return clean[:64]


class StorageManager:
    """
    Manages structured file storage under the 'uploads/' directory.
    Directory Structure:
      uploads/
      ├── drivers/
      │   └── {driver_id}/
      │       └── {request_id}/
      │           ├── originals/
      │           │   ├── selfie_original.jpg
      │           │   ├── license_original.jpg
      │           │   ├── license_back_original.jpg
      │           │   └── vehicle_original.jpg
      │           ├── cropped/
      │           │   ├── selfie_face_crop.webp
      │           │   ├── dl_face_crop_sanitized.webp
      │           │   └── vehicle_plate_crop.webp
      │           ├── compressed/
      │           │   ├── selfie_compressed.webp
      │           │   ├── license_compressed.webp
      │           │   ├── license_back_compressed.webp
      │           │   └── vehicle_compressed.webp
      │           └── session_metadata.json
      └── previews/
          └── {preview_id}/
              ├── originals/
              │   └── license_original.jpg
              ├── cropped/
              │   └── dl_face_crop_sanitized.webp
              └── compressed/
                  └── license_compressed.webp
    """

    def __init__(self, base_dir: Optional[Union[str, Path]] = None) -> None:
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        else:
            # Default to an 'uploads' directory sibling to this script or in storage/
            self.base_dir = Path(__file__).parent.resolve() / "uploads"

        self.drivers_dir = self.base_dir / "drivers"
        self.previews_dir = self.base_dir / "previews"
        self._init_directories()

    def _init_directories(self) -> None:
        """Create root uploads structure if not present."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.drivers_dir.mkdir(parents=True, exist_ok=True)
        self.previews_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized storage at: {self.base_dir}")

    def save_image_file(
        self,
        target_path: Path,
        img_bgr: np.ndarray,
        quality: int = 90
    ) -> Optional[str]:
        """Save a BGR numpy array to disk as WebP, JPEG, or PNG based on target extension."""
        if img_bgr is None or img_bgr.size == 0:
            return None
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            ext = target_path.suffix.lower()
            if ext == ".webp":
                params = [int(cv2.IMWRITE_WEBP_QUALITY), quality]
            elif ext in [".jpg", ".jpeg"]:
                params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            elif ext == ".png":
                params = [int(cv2.IMWRITE_PNG_COMPRESSION), 4]
            else:
                params = []
            cv2.imwrite(str(target_path), img_bgr, params)
            return str(target_path)
        except Exception as e:
            logger.error(f"Failed to save image to {target_path}: {e}")
            return None

    def save_verification_session_images(
        self,
        driver_id: str,
        request_id: str,
        original_images: Dict[str, Optional[np.ndarray]],
        cropped_images: Optional[Dict[str, Optional[np.ndarray]]] = None,
        compressed_images: Optional[Dict[str, Optional[np.ndarray]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Persist images in organized nested subfolders:
          uploads/drivers/{driver_id}/{request_id}/originals/    (Raw uploaded photos)
          uploads/drivers/{driver_id}/{request_id}/cropped/      (Privacy-isolated face/plate crops)
          uploads/drivers/{driver_id}/{request_id}/compressed/   (WebP normalized photos post-verification)
        """
        clean_driver = sanitize_folder_name(driver_id)
        clean_request = sanitize_folder_name(request_id)

        session_root = self.drivers_dir / clean_driver / clean_request
        orig_dir = session_root / "originals"
        crop_dir = session_root / "cropped"
        comp_dir = session_root / "compressed"

        orig_dir.mkdir(parents=True, exist_ok=True)
        crop_dir.mkdir(parents=True, exist_ok=True)
        comp_dir.mkdir(parents=True, exist_ok=True)

        saved_records: Dict[str, Any] = {
            "session_directory": str(session_root),
            "originals_folder": str(orig_dir),
            "cropped_folder": str(crop_dir),
            "compressed_folder": str(comp_dir),
            "original_files": {},
            "cropped_files": {},
            "compressed_files": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Save Raw Original Images
        orig_mapping = {
            "selfie": "selfie_original.jpg",
            "license": "license_original.jpg",
            "license_back": "license_back_original.jpg",
            "vehicle": "vehicle_original.jpg",
        }
        for key, fname in orig_mapping.items():
            img = original_images.get(key)
            if img is not None and img.size > 0:
                dest = orig_dir / fname
                saved_path = self.save_image_file(dest, img)
                if saved_path:
                    saved_records["original_files"][key] = {
                        "filename": fname,
                        "relative_path": f"drivers/{clean_driver}/{clean_request}/originals/{fname}",
                        "absolute_path": saved_path,
                        "resolution": f"{img.shape[1]}x{img.shape[0]}",
                        "size_bytes": os.path.getsize(saved_path) if os.path.exists(saved_path) else 0,
                    }

        # 2. Save Cropped & Sanitized Images (Face & Plate Crops)
        if cropped_images:
            crop_mapping = {
                "selfie_face": "selfie_face_crop.webp",
                "dl_face": "dl_face_crop_sanitized.webp",
                "vehicle_plate": "vehicle_plate_crop.webp",
            }
            for key, fname in crop_mapping.items():
                img = cropped_images.get(key)
                if img is not None and img.size > 0:
                    dest = crop_dir / fname
                    saved_path = self.save_image_file(dest, img, quality=90)
                    if saved_path:
                        saved_records["cropped_files"][key] = {
                            "filename": fname,
                            "relative_path": f"drivers/{clean_driver}/{clean_request}/cropped/{fname}",
                            "absolute_path": saved_path,
                            "resolution": f"{img.shape[1]}x{img.shape[0]}",
                            "size_bytes": os.path.getsize(saved_path) if os.path.exists(saved_path) else 0,
                        }

        # 3. Save WebP Compressed Normalized Images (Post-Verification)
        if compressed_images:
            comp_mapping = {
                "selfie": "selfie_compressed.webp",
                "license": "license_compressed.webp",
                "license_back": "license_back_compressed.webp",
                "vehicle": "vehicle_compressed.webp",
            }
            for key, fname in comp_mapping.items():
                img = compressed_images.get(key)
                if img is not None and img.size > 0:
                    dest = comp_dir / fname
                    q = 80 if key == "selfie" else (70 if "license" in key else 85)
                    saved_path = self.save_image_file(dest, img, quality=q)
                    if saved_path:
                        saved_records["compressed_files"][key] = {
                            "filename": fname,
                            "relative_path": f"drivers/{clean_driver}/{clean_request}/compressed/{fname}",
                            "absolute_path": saved_path,
                            "resolution": f"{img.shape[1]}x{img.shape[0]}",
                            "size_bytes": os.path.getsize(saved_path) if os.path.exists(saved_path) else 0,
                        }

        # 4. Save Session Metadata JSON
        try:
            meta_payload = {
                "driver_id": driver_id,
                "request_id": request_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "storage_structure": saved_records,
                "custom_metadata": metadata or {},
            }
            meta_path = session_root / "session_metadata.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta_payload, f, indent=2)
            saved_records["metadata_file"] = str(meta_path)
        except Exception as e:
            logger.warning(f"Could not write metadata.json: {e}")

        logger.info(f"Saved session images to: {session_root}")
        return saved_records

    def save_preview_images(
        self,
        preview_id: str,
        original_img: Optional[np.ndarray],
        cropped_img: Optional[np.ndarray],
        compressed_img: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Persist standalone privacy crop preview images:
          uploads/previews/{preview_id}/originals/
          uploads/previews/{preview_id}/cropped/
          uploads/previews/{preview_id}/compressed/
        """
        clean_id = sanitize_folder_name(preview_id)
        preview_root = self.previews_dir / clean_id
        orig_dir = preview_root / "originals"
        crop_dir = preview_root / "cropped"
        comp_dir = preview_root / "compressed"

        orig_dir.mkdir(parents=True, exist_ok=True)
        crop_dir.mkdir(parents=True, exist_ok=True)
        comp_dir.mkdir(parents=True, exist_ok=True)

        res: Dict[str, Any] = {
            "preview_directory": str(preview_root),
            "original_file": None,
            "cropped_file": None,
            "compressed_file": None,
        }

        if original_img is not None and original_img.size > 0:
            dest = orig_dir / "license_original.jpg"
            saved = self.save_image_file(dest, original_img)
            if saved:
                res["original_file"] = f"previews/{clean_id}/originals/license_original.jpg"

        if cropped_img is not None and cropped_img.size > 0:
            dest = crop_dir / "dl_face_crop_sanitized.webp"
            saved = self.save_image_file(dest, cropped_img, quality=90)
            if saved:
                res["cropped_file"] = f"previews/{clean_id}/cropped/dl_face_crop_sanitized.webp"

        if compressed_img is not None and compressed_img.size > 0:
            dest = comp_dir / "license_compressed.webp"
            saved = self.save_image_file(dest, compressed_img, quality=85)
            if saved:
                res["compressed_file"] = f"previews/{clean_id}/compressed/license_compressed.webp"

        return res

    def list_verification_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Scan uploads/drivers/ to retrieve past verification sessions metadata."""
        sessions = []
        if not self.drivers_dir.exists():
            return sessions

        try:
            req_folders = []
            for driver_folder in self.drivers_dir.iterdir():
                if not driver_folder.is_dir():
                    continue
                for req_folder in driver_folder.iterdir():
                    if req_folder.is_dir():
                        req_folders.append(req_folder)

            req_folders.sort(key=lambda p: p.stat().st_mtime, reverse=True)

            for req_folder in req_folders[:limit]:
                meta_file = req_folder / "session_metadata.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            sessions.append(json.load(f))
                    except Exception as e:
                        logger.debug(f"Could not read metadata at {meta_file}: {e}")
                else:
                    sessions.append({
                        "driver_id": req_folder.parent.name,
                        "request_id": req_folder.name,
                        "created_at": datetime.fromtimestamp(req_folder.stat().st_mtime, timezone.utc).isoformat(),
                        "storage_structure": {},
                        "custom_metadata": {},
                    })
        except Exception as e:
            logger.error(f"Error scanning verification sessions: {e}")

        return sessions

    def get_session_details(self, driver_id: str, request_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve comprehensive metadata and file map for a specific verification session."""
        clean_driver = sanitize_folder_name(driver_id)
        clean_request = sanitize_folder_name(request_id)
        session_root = self.drivers_dir / clean_driver / clean_request

        if not session_root.exists():
            return None

        meta_file = session_root / "session_metadata.json"
        data: Dict[str, Any] = {}
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read session metadata {meta_file}: {e}")

        files_map = {"originals": [], "cropped": [], "compressed": []}
        for sub in ["originals", "cropped", "compressed"]:
            sub_p = session_root / sub
            if sub_p.exists():
                for fp in sub_p.iterdir():
                    if fp.is_file():
                        files_map[sub].append({
                            "name": fp.name,
                            "relative_path": f"drivers/{clean_driver}/{clean_request}/{sub}/{fp.name}",
                            "size_bytes": fp.stat().st_size,
                            "extension": fp.suffix.lower(),
                        })

        data["live_files_map"] = files_map
        return data


# Global singleton instance
storage_manager = StorageManager()
