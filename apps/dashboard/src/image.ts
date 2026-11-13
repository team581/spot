import { fromBinary } from '@bufbuild/protobuf';
import { CompressedImageSchema } from './gen/foxglove/CompressedImage_pb';

export const decodeImage = (payload: Uint8Array) => fromBinary(CompressedImageSchema, payload).data;
