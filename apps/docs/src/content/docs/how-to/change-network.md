---
title: Change Spot's network settings
description: Point Spot at a different NetworkTables server, or change its Ethernet addressing.
---

Network settings live on the Jetson, not in `spot.toml`.
Change them on the dashboard's **Network** page.

## Connect to a simulator or laptop

Enter the machine's address in **NetworkTables server** and choose **Save**.
Clear it to go back to the roboRIO.

## Use a static address

1. Under **Ethernet**, set **Addressing** to **Static**, enter the address, and choose **Try change**.
2. Reconnect to the dashboard at the new address and choose **Confirm** before the countdown ends.

If you can't reach the new address, wait for the countdown.
Spot reverts on its own.
The maintenance address, `10.5.81.11`, works throughout.
