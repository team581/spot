---
title: About USB camera bandwidth
description: Why camera streams can run out of USB bandwidth before Spot starts processing frames.
---

A USB 3 port carries USB 2.0 and SuperSpeed on separate wires. A Swyft camera is a USB 2.0 device, so it connects at `480M` even in a blue port or through a USB 3 cable. That speed is normal and doesn't indicate a bad cable.

On the J401, four USB-A sockets feed one hub. USB 2.0 cameras on those sockets share its 480 Mb/s uplink. SuperSpeed devices share a separate 5 Gb/s uplink. Both figures are signaling rates, not usable throughput. Devices can report the same link speed even when they compete for the same uplink.

## Why a stream can fail before detection

The USB host reserves time on the bus for each Swyft video stream. The reservation can be larger than the actual MJPEG traffic. If the host can't fit the reservation, the camera fails to start before Spot receives a frame.

## What adds capacity

Separate root ports avoid sharing the same hub uplink. A hub on an existing port adds sockets, not another path back to the host, even if it has its own power supply.

A native SuperSpeed camera can use the faster path if it offers UVC MJPEG at the intended mode. A PCIe USB controller can add root ports if the carrier has a compatible expansion slot. GMSL2 and Ethernet cameras bypass USB, but Spot doesn't capture either natively.

See the [J401 port map](../../reference/jetson/#usb-host-ports) and [recommended wiring](../../how-to/add-camera/#wire-multiple-swyft-cameras).
