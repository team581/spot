declare module '@spot/camera-viewer' {
	const math: {
		cameraAngles: (quaternion: number[]) => number[];
		cameraQuaternion: (yaw: number, pitch: number, roll: number) => number[];
	};
	export default math;
}
