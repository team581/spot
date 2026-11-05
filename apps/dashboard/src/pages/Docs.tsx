import { useEffect, useRef } from 'react';
import { useLocation, useNavigate, useParams } from '@tanstack/react-router';
/** Show the bundled docs site in a pane, keeping the dashboard URL in step with the page it shows. */
export default function Docs() {
	const splat = useParams({ from: '/help/$', select: (params) => params._splat ?? '' }),
		hash = useLocation({ select: (location) => location.hash }),
		navigate = useNavigate(),
		frame = useRef<HTMLIFrameElement>(null),
		src = '/docs/' + splat + (hash ? '#' + hash : '');
	useEffect(() => {
		const location = frame.current?.contentWindow?.location;
		if (location && location.pathname + location.hash !== src) location.replace(src);
	}, [src]);
	const follow = () => {
		const location = frame.current?.contentWindow?.location;
		if (!location?.pathname.startsWith('/docs/')) return;
		void navigate({
			to: '/help/$',
			params: { _splat: location.pathname.slice('/docs/'.length) },
			hash: location.hash.slice(1),
			replace: true,
		});
	};
	return (
		<iframe
			ref={frame}
			title="Documentation"
			className="w-full flex-1 border-0"
			onLoad={() => {
				follow();
				frame.current?.contentWindow?.addEventListener('hashchange', follow);
			}}
		/>
	);
}
