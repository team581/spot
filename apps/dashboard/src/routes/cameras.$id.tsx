import { createFileRoute, Link, Outlet } from '@tanstack/react-router';
import { useCamera } from '../queries';
import CameraName from '../pages/CameraName';
export const Route = createFileRoute('/cameras/$id')({ component: CameraLayout });
function CameraLayout() {
	const camera = useCamera(Route.useParams().id);
	if (!camera)
		return (
			<>
				<h1 className="font-heading text-2xl font-semibold">Camera unavailable</h1>
				<p>
					The configured camera may be disconnected. <Link to="/cameras">Open Cameras</Link>
				</p>
			</>
		);
	if (!camera.logical_name && !camera.standalone_setup) return <CameraName key={camera.identity} camera={camera} />;
	return <Outlet />;
}
