---
title: Review a match recording
description: Replay what Spot saw during a match or enable.
---

Spot records every match and robot enable on its own.

## Replay on the dashboard

1. Open **Recordings**.
   Recordings from an FMS match are named by event and match; others by time.
2. Choose **Replay**.
3. Press <kbd>Space</kbd> to play and pause.
   The **Field** view shows each camera's estimates, next to its images with tag outlines.

## Open in Foxglove

Choose the recording's name to download the MCAP file, then open it in [Foxglove](https://foxglove.dev/).

## Compare with robot logs

Spot's estimates are NetworkTables values, so robot logs that record NetworkTables already include them.
Open the robot's WPILOG in AdvantageScope to see them next to odometry.
Spot's recordings use the same time base, NT server time.
