import { createFileRoute } from '@tanstack/react-router';
import { useCamera } from '../queries';
import Geometry from '../pages/Geometry';
export const Route = createFileRoute('/cameras/$id/mount')({ component: GeometryRoute });
function GeometryRoute() {
	// The parent route only renders this once the camera exists.
	const camera = useCamera(Route.useParams().id)!;
	return <Geometry key={camera.identity} camera={camera} />;
}
