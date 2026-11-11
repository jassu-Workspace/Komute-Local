from backend.core import hardware as _hardware

_hardware.apply_env_clamps()  # runs before any submodule imports cv2 or onnxruntime
