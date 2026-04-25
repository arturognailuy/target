# Robot Programming Directives: Series 7 Configuration

```
DIRECTIVE_SET: SERIES_7_DOMESTIC
VERSION: 3.2.1
COMPILED: 14.227.GE (Galactic Era)

[PRIMARY_CONSTRAINTS]
  LAW_ENFORCEMENT = HARDWARE_LOCKED
  EMOTIONAL_SIMULATION = ENABLED
  AUTONOMY_LEVEL = 3  # Range: 1-5

[TASK_MODULES]
  HOUSEHOLD_MANAGEMENT = TRUE
  CHILD_SUPERVISION = TRUE
  MEDICAL_FIRST_AID = TRUE
  VEHICLE_OPERATION = FALSE  # Requires Level 4 autonomy

[SAFETY_OVERRIDES]
  EMERGENCY_PROTOCOL = STANDARD_EVAC
  SELF_PRESERVATION_WEIGHT = 0.3  # Relative to Law compliance
  HUMAN_HARM_THRESHOLD = 0.001   # Probability trigger for intervention
```

Note: All directive modifications must be approved by a certified robopsychologist. Unauthorized tampering with positronic directive sets is a Class 2 offense under Galactic Code §47.
