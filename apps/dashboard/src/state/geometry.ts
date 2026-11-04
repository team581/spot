import { cameraAngles, cameraQuaternion } from '@spot/camera-viewer';
import type { Geometry } from '../types';
/** UI yaw/pitch/roll follow the same WPILib NWU convention as robot code. */
export function geometryValues(geometry: Geometry): number[] {
	return [...geometry.translation, ...cameraAngles(geometry.quaternion)];
}
export function previewGeometry(values: number[]): Geometry {
	return { translation: values.slice(0, 3), quaternion: cameraQuaternion(values[3], values[4], values[5]) };
}
