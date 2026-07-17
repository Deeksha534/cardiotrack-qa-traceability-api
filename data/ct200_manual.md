CardioTrack CT-200 Home Blood Pressure Monitor
Technical & Service Manual — Revision A

This manual is intended for service technicians and QA engineers. It is not a
consumer quick-start guide. Read the safety section before operating the device.

# 1. Overview

The CardioTrack CT-200 is an oscillometric home blood pressure monitor. It
measures systolic pressure, diastolic pressure, and pulse rate from the upper
arm using an inflatable cuff.

## 1.1 Intended Use

The device is intended for non-invasive measurement of arterial blood pressure
in adult patients at home. It is not intended for neonatal use.

## 1.2 Device Components

The device ships with the main unit, an adult cuff (22–42 cm), and 4 AA
batteries.

# 2. Safety

Failure to observe these warnings may result in inaccurate readings or patient
harm.

## 2.1 Cuff Pressure Limits

The cuff must never exceed 300 mmHg. If measured cuff pressure exceeds
300 mmHg, the device must display error E3 and auto-deflate within 2 seconds.

## 2.1 Cuff Pressure Limits

For patients with fragile skin, the maximum recommended inflation pressure is
280 mmHg. This overrides the general limit above for the fragile-skin patient
profile.

## 2.2 Electrical Safety

Do not operate the device while charging. Use only the supplied power adapter.

# 3. Operation

### 3.1.1 Starting a Measurement

Press the START button once. The cuff inflates automatically to 180 mmHg and
then deflates while measuring. Remain still and do not talk during measurement.

## 3.2 Reading Results

Systolic and diastolic values appear on the top line. Pulse appears on the
bottom line with a heart icon.

# 4. Error Codes

The device reports faults through numbered error codes on the display.

## 4.1 Error Code Table

The following pseudocode shows how the firmware selects an error code. Note that
the lines beginning with `#` below are code comments, not document headings:

```
# error selection routine
if cuff_pressure > 300:
    # E3: overpressure
    display("E3")
    deflate()
# E1: cuff loose
elif not cuff_detected:
    display("E1")
```

E1 indicates a loose cuff. E3 indicates overpressure. E5 indicates a
measurement timeout after 120 seconds.

## 4.2 Clearing Errors

Remove and reinsert the batteries to clear a latched error. If the error
persists, return the unit for service.

# 5. Maintenance

Wipe the cuff with a damp cloth. Do not immerse the main unit in water.
