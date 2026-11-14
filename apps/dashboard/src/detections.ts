/** The `/<camera>/detections` messages Spot logs live and in recordings. */

interface Tag {
	id: number;
	/** Image pixels: bottom-left, bottom-right, top-right, top-left. */
	corners: [number, number][];
	hamming: number;
	decision_margin: number;
	/** Whether the tag contributed to the pose estimate. */
	used: boolean;
}
export interface Candidate {
	x: number;
	y: number;
	z: number;
	/** Degrees. */
	roll: number;
	/** Degrees. */
	pitch: number;
	/** Degrees. */
	yaw: number;
	/** Reprojection error in pixels. */
	error: number;
}
export interface Detections {
	width: number;
	height: number;
	tags: Tag[];
	estimate: null | {
		primary: Candidate;
		alternate: Candidate | null;
		average_tag_distance: number;
		tag_area: number;
	};
}

const text = new TextDecoder();
// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- Spot serializes this topic from the backend Detections schema.
export const decodeDetections = (payload: Uint8Array) => JSON.parse(text.decode(payload)) as Detections;
