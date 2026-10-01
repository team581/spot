
The main goal of the vision solution is to replace the existing solution for detecting April Tags (Limelight).
## Hardware
- Jetson
- USB Camera

## Inspiration
- [Team 766's 971 Fork of CUDA vision solution](https://github.com/Team766/apriltags_cuda?)
	- original: [Team 971](https://github.com/frc971/971-Robot-Code)
	- very useful for detection code
- 6328 Northstar 
	- Mainly for structure
- Potential: 190


### 971 Notes
- Good for detection reference
- Uses just CUDA for quad fitting
### 6328 Northstar Notes
- May be good as a general structure reference
- Used GStreamer for image acquisition/decoding
- NT for config/stream interfaces
- Global shutter + low exposure (stuff we already do from limelight)
- NT4 queues so multiple frames in one 20ms loop aren't dropped
	- **how do they decide which to use?**
- roboRIO side pose filtering (basically how we deal with limelight poses)
	- useful for robot state, gyro, etc
- They send all the poses, even ambiguous ones, so they can further debug, which I think makes sense
	- Basically we should have a way to see what poses we filtered out
- 190 and 6328 avoid JPEG compression, using USB3 and uncompressed YUYV to keep corners of tags intact and avoid decoding overhead
- 

### 254 Inspiration Notes
- Cut out corners edges of camera frame if you have tags in the center region

### Jonah’s Tag Result Ingestion Rec
1. have spot write all vision results to an array/map on NT
2. have rio report it's latest processed timestamp to NT
3. spot removes entries older than that timestamp
