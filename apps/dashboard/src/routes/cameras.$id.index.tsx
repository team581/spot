import { createFileRoute } from '@tanstack/react-router';
import { useCamera } from '../queries';
import CameraDetail from '../pages/CameraDetail';
export const Route = createFileRoute('/cameras/$id/')({ component: CameraDetailRoute });
function CameraDetailRoute() {
	// The parent route only renders this once the camera exists.
	const camera = useCamera(Route.useParams().id)!;
	return <CameraDetail key={camera.identity + '/' + camera.logical_name} camera={camera} />;
}
