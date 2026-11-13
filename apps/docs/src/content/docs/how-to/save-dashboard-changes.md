---
title: Save dashboard changes to robot code
description: Copy dashboard overrides into spot.toml so they survive a reinstall.
---

Dashboard changes are stored on the Jetson as overrides.
Save them to robot code before a reinstall or a Jetson swap, and before competition.

1. Open **Config**.
   **Overrides** lists each change next to the robot code value.
2. Choose **Copy** on **Merged config**.
3. In `src/main/deploy/spot.toml`, replace everything below the `#:schema` line with it.
4. Deploy robot code.

Once robot code matches, Spot deletes the overrides and the dashboard's overrides warning goes away.

To drop overrides instead, choose **Discard overrides**.

To try a config without deploying robot code, paste it into **Paste config** and choose **Apply**.
It's saved as overrides, so discarding them returns to robot code's config.
