import { createFileRoute } from '@tanstack/react-router';
import Recordings from '../pages/Recordings';

export const Route = createFileRoute('/downloads')({ component: Recordings });
