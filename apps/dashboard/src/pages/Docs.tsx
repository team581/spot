import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from '@tanstack/react-router';
/** Show the bundled docs site in a pane, keeping the dashboard URL in step with the page it shows. */
export default function Docs() {
	// Read the path and hash together; they can update separately while a navigation is pending.
	const src = useLocation({
		select: ({ pathname, hash }) => {
			// Every docs page URL has a trailing slash.
			const page = pathname.slice('/help/'.length).replace(/[^/]$/, '$&/');
			return `/docs/${page}${hash ? `#${hash}` : ''}`;
		},
	});
	const navigate = useNavigate();
	const frame = useRef<HTMLIFrameElement>(null);
	useEffect(() => {
		const location = frame.current?.contentWindow?.location;
		if (location && location.pathname + location.hash !== src) {
			location.replace(src);
		}
	}, [src]);
	const follow = () => {
		const location = frame.current?.contentWindow?.location;
		if (!location?.pathname.startsWith('/docs/')) {
			return;
		}
		void navigate({
			hash: location.hash.slice(1),
			params: { _splat: location.pathname.slice('/docs/'.length) },
			replace: true,
			to: '/help/$',
		});
	};
	return (
		// oxlint-disable-next-line react/iframe-missing-sandbox -- Our bundled docs use scripts and same-origin access to synchronize navigation.
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
