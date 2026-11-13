import { createFileRoute } from '@tanstack/react-router';
import Calibration from '../pages/Calibration';

export const Route = createFileRoute('/calibration')({ component: Calibration });
