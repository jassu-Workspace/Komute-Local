# Komüte-Local Discovery Quiz

Answer each question in 1–3 lines under **Your answer**. "Don't know" is a valid answer. It tells us what to research.
Reply with the question number and your answer, for example `A3: …`. You can answer in any order.

---

## Part A. Concepts

**A1.** What does a face-matching model output when it compares two faces? What does a higher number mean?
Your answer:

**A2.** Two mistakes are possible: approving a wrong person, and rejecting the right person. Which is worse for this product, and why?
Your answer:

**A3.** If we make the match threshold stricter, what happens to each of those two mistakes?
Your answer:

**A4.** What is "liveness" (presentation-attack detection)? Name two ways someone could fool a face check without it.
Your answer:

**A5.** A driver licence barcode holds the person's data. Does it prove the licence is real? Why or why not?
Your answer:

**A6.** Why do we trust the barcode more than reading the printed text with OCR?
Your answer:

**A7.** Why is matching a 25-year-old photo to a 45-year-old face harder than matching two recent photos?
Your answer:

**A8.** What does it mean to shrink a model (quantization), and what is the risk?
Your answer:

**A9.** What is the difference between a model's accuracy on its own training data and its accuracy on our real users?
Your answer:

**A10.** Why can a plate reader confuse `O` and `0`, or `I` and `1`? How could we stop that?
Your answer:

---

## Part B. How would we solve it?

**B1.** A user's photo of the licence is blurry, dark or tilted. What steps should the system take? Should it reject, ask for a retake, or try harder?
Your answer:

**B2.** Someone holds up a printed photo or a phone screen of another person's face. What steps should the system take to catch it?
Your answer:

**B3.** Someone makes a fake licence with a barcode that matches their made-up details. What extra checks could catch it?
Your answer:

**B4.** The face score lands just under the threshold. What should happen next, and who decides?
Your answer:

**B5.** The memory limit is 1.3 GB and the model files total about 300 MB. List the steps you would follow to find where memory goes and keep it under the limit.
Your answer:

**B6.** The plate in the photo reads `ABC123` but the driver registered `ABC 123`. What cleaning rules should apply before comparing? What about `ABC1234`?
Your answer:

**B7.** The car is dark grey but the photo shows blue sky reflecting on it. How would you decide the car's real colour?
Your answer:

**B8.** The driver's name on the application is `JOHN A SMITH`. The barcode says `SMITH, JOHN ANDREW`. What counts as a match? What counts as a mismatch?
Your answer:

**B9.** The same request arrives twice because the host app retried. What should the module do?
Your answer:

**B10.** One of the models fails to load at startup. What should the module do, and what must it never do?
Your answer:

---

## Part C. Product decisions

**C1.** Which jurisdictions must work on day one: Ontario only, all Canadian provinces, US states, or others? Which are the most important?
Your answer:

**C2.** What is the real-world flow? Does the driver take the photos on a phone through the host app, or does an operator upload them?
Your answer:

**C3.** What does the host app need back from us? Pick from: decision, reason codes, scores, cropped images, a full audit record.
Your answer:

**C4.** What should happen to the raw photos after verification? Delete right away, keep for a set number of days, or keep forever? Why?
Your answer:

**C5.** Which images are we allowed to keep for audit or dispute handling, and for how long?
Your answer:

**C6.** Does the plate have to match the vehicle record exactly, or is a one-character difference acceptable? What is the risk either way?
Your answer:

**C7.** Is the vehicle colour a hard requirement or only a warning sign? What would you do with a colour mismatch?
Your answer:

**C8.** How long may one verification take before the host app gives up? What is your target?
Your answer:

**C9.** Should a REVIEW result (a borderline case) exist? If yes, who looks at it, and what do they see?
Your answer:

**C10.** What is the worst thing that could go wrong after launch, for the driver and for the business?
Your answer:

---

## Part D. Proof and quality

**D1.** What data could we use to test the system before launch? Do you have real licences, selfies and vehicle photos, or synthetic ones?
Your answer:

**D2.** What false-approve rate and what false-reject rate would you accept at launch?
Your answer:

**D3.** How would we know after launch that accuracy is getting worse?
Your answer:

**D4.** Which three fraud attempts worry you most, in order?
Your answer:

**D5.** What would make you say "this is 10/10, ship it"? List the checks that must pass.
Your answer:

**D6.** What would make you say "stop, do not ship"?
Your answer:
