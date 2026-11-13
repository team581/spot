import { createFileRoute } from '@tanstack/react-router';
import Replay from '../pages/Replay';

export const Route = createFileRoute('/downloads_/$name')({ component: Replay });
