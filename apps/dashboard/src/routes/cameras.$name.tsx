import { createFileRoute } from '@tanstack/react-router';
import CameraDetail from '../pages/CameraDetail';

export const Route = createFileRoute('/cameras/$name')({ component: CameraDetail });
