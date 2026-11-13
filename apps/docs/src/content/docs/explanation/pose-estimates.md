---
title: About pose estimates
description: How Spot turns a camera frame into a robot pose, and what it leaves to robot code.
---

## One frame, one camera, one estimate

Spot is stateless.
Each estimate comes from one frame of one camera, with no smoothing over time and no fusion across cameras.
Robot code already has a pose estimator that fuses odometry, gyro, and vision with proper timing; doing a second, weaker version of that on the Jetson would only hide information from it.

The same reasoning puts every trust decision in robot code.
Spot drops a tag only when it isn't in the field layout, is in `ignored_tags`, or was seen by an uncalibrated camera.
It doesn't reject estimates for being far away, ambiguous, or off the field.
Instead each estimate carries what robot code needs to judge it: reprojection error, tag count, distance, and image area.
Tuning standard deviations from those is robot code's job, where it can be changed and logged with the rest of the robot.

## Solving the pose

Spot fits all of a frame's tags at once, using the camera's mount to solve for the robot directly rather than solving for the camera and transforming afterward.
The solve is full 6-DOF: x, y, z, roll, pitch, and yaw.

A single far tag barely constrains height and tilt.
Small pixel errors can swing them wildly, and a free solver will happily return a robot floating a meter above the carpet.
So the solver starts from a robot flat on the floor and adds a soft prior toward it (σ of 0.1 m in height and 5° in roll and pitch).
Tags that clearly show a tilt, such as when the robot is climbing, still win over the prior.

Even with the prior, height, roll, and pitch are the noisiest parts of an estimate.
Most robot code should keep x, y, and yaw and trust the gyro for the rest.

## Primary and alternate

A single tag seen nearly head-on has two poses that fit it almost equally well, mirror images across the tag's plane.
Spot can't tell them apart from the image, so it reports both: the better fit as `primary` and the other as `alternate`.
Robot code can pick between them with information Spot doesn't have, usually the gyro's heading.
Spot only reports an alternate that fits within three times the primary's error.
With several tags in view the mirror pose fits far worse, so `alternate` is usually absent.

## Timestamps

Each estimate's NetworkTables timestamp is the frame's capture time, from the kernel's V4L2 buffer timestamp converted to NT server time.
That is the time `addVisionMeasurement` wants, so there is no latency field to subtract and no per-camera latency to tune.
This is also why Spot publishes nothing until its clock is synced: an estimate with the wrong timestamp is worse than none.

## Latency over throughput

Capture and detection run separately for each camera, and detection always takes the newest frame.
When detection can't keep up, Spot drops frames rather than queueing them.
A queue would deliver every frame, but each one later than the last, and a pose estimator gains more from one fresh estimate than from several stale ones.
Dropped frames are counted in the camera's status, and a camera that keeps dropping reports `falling_behind`.

## The detector

Spot uses its own tag36h11 detector, borrowing ideas from NAPA and Team 971's CUDA detector.
The camera's MJPEG frames are decoded on the Jetson's hardware JPEG engine, and the dense, per-pixel work runs on the GPU straight from that output.
Only tag-shaped candidates reach the CPU for edge fitting and decoding.
When the camera is calibrated, edges are fit in undistorted space, which matters most for tags near the image's edges.

`spot-vision corpus` scores the detector's accuracy and speed on labelled frames, so detector changes can be measured instead of judged by eye.
