import { useEffect, useRef } from 'react';
import { fromBinary } from '@bufbuild/protobuf';
import { CompressedImageSchema } from './gen/foxglove/CompressedImage_pb';

export const decodeImage = (payload: Uint8Array) => fromBinary(CompressedImageSchema, payload).data;

/**
 * Closes bitmaps once a committed render stops using them, and all of them on unmount. Child effects
 * run first, so components below have already drawn the replacements.
 */
export function useCloseReplaced(bitmaps: ImageBitmap[]) {
	const shown = useRef<ImageBitmap[]>([]);
	useEffect(() => {
		for (const bitmap of shown.current) {
			if (!bitmaps.includes(bitmap)) {
				bitmap.close();
			}
		}
		shown.current = bitmaps;
	});
	useEffect(
		() => () => {
			for (const bitmap of shown.current) {
				bitmap.close();
			}
		},
		[],
	);
}
