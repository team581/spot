import { lazy, Suspense, useEffect, useState } from 'react';
import { useDashboard, useServiceError } from './dashboard';
import { useStatus } from './queries';
import { date, Icon } from './components/common';
import { ThemeMenu } from './components/ThemeMenu';
import Overview from './pages/Overview';
const CameraName = lazy(() => import('./pages/CameraName'));
const CameraDetail = lazy(() => import('./pages/CameraDetail'));
const Geometry = lazy(() => import('./pages/Geometry'));
const Calibration = lazy(() => import('./pages/Calibration'));
const Network = lazy(() => import('./pages/Network'));
const System = lazy(() => import('./pages/System'));
function route() {
	const parts = location.hash
		.slice(1)
		.split('/')
		.map((part) => {
			try {
				return decodeURIComponent(part);
			} catch {
				return part;
			}
		});
	return { page: parts[0] || 'overview', id: parts[1], tab: parts[2] };
}
export default function App() {
	const { message } = useDashboard(),
		status = useStatus(),
		serviceError = useServiceError(),
		[current, setCurrent] = useState(route);
	useEffect(() => {
		const changed = () => setCurrent(route());
		addEventListener('hashchange', changed);
		return () => removeEventListener('hashchange', changed);
	}, []);
	const camera = status.cameras.find((c) => c.identity === current.id);
	const page =
		current.page === 'overview' || current.page === 'cameras' ? (
			<Overview page={current.page} />
		) : current.page === 'camera' && camera ? (
			!camera.logical_name && !camera.standalone_setup ? (
				<CameraName key={camera.identity} camera={camera} />
			) : current.tab === 'geometry' ? (
				<Geometry key={camera.identity} camera={camera} />
			) : (
				<CameraDetail
					key={camera.identity + '/' + Boolean(camera.logical_name) + '/' + Boolean(camera.standalone_setup)}
					camera={camera}
				/>
			)
		) : current.page === 'calibration' ? (
			<Calibration results={current.id === 'results'} />
		) : current.page === 'network' ? (
			<Network />
		) : current.page === 'system' ? (
			<System />
		) : (
			<>
				<h1>Camera unavailable</h1>
				<p>
					The configured camera may be disconnected. <a href="#cameras">Open Cameras</a>
				</p>
			</>
		);
	return (
		<>
			<a className="skip" href="#main">
				Skip to content
			</a>
			<aside id="sidebar" aria-label="Main navigation">
				<a className="brand" href="#overview">
					<img src="/blazing-bulldogs.svg" alt="Blazing Bulldogs" />
					<strong>Spot</strong>
				</a>
				<nav id="nav">
					{['overview', 'cameras'].map((name) => (
						<a
							key={name}
							href={'#' + name}
							className={current.page === name ? 'active' : ''}
							title={name === 'overview' ? 'Overview' : 'Cameras'}
							aria-label={name === 'overview' ? 'Overview' : 'Cameras'}
						>
							<Icon name={name} />
							<span className="nav-label">{name === 'overview' ? 'Overview' : 'Cameras'}</span>
						</a>
					))}
					{status.cameras.map((c) => {
						const warnings = [];
						if (c.health !== 'Disabled' && !c.logical_name) warnings.push('Choose a code-defined name');
						if (c.health !== 'Disabled' && c.logical_name && !c.calibrated) warnings.push('Calibration required');
						if (c.health !== 'Disabled' && !c.connected)
							warnings.push(c.present ? c.fault || 'Waiting for image' : 'Disconnected');
						return (
							<a
								key={c.identity}
								className={'camera-entry ' + (current.page === 'camera' && current.id === c.identity ? 'active' : '')}
								href={'#camera/' + encodeURIComponent(c.identity)}
								aria-label={c.name + (warnings.length ? ': ' + warnings.join('; ') : '')}
							>
								<span>{c.name}</span>
								{warnings.map((w) => (
									<span key={w} className="warning" role="img" aria-label={w} title={w}>
										⚠
									</span>
								))}
							</a>
						);
					})}
					{['calibration', 'network', 'system'].map((name) => (
						<a
							key={name}
							href={'#' + name}
							className={(name === 'calibration' ? 'section-gap ' : '') + (current.page === name ? 'active' : '')}
							title={name[0].toUpperCase() + name.slice(1)}
							aria-label={name[0].toUpperCase() + name.slice(1)}
						>
							<Icon name={name} />
							<span className="nav-label">{name[0].toUpperCase() + name.slice(1)}</span>
						</a>
					))}
					<a href="/docs/" title="Docs" aria-label="Docs">
						<Icon name="docs" />
						<span className="nav-label">Docs</span>
					</a>
				</nav>
				<footer>
					<ThemeMenu />
					<div id="updated">
						{status.software.process_started_at
							? 'Started ' + date(status.software.process_started_at)
							: 'Time unavailable'}
					</div>
					<small id="software-version" title={status.software.package_path}>
						{status.software.version ? 'Spot ' + status.software.version : 'Development'}
					</small>
				</footer>
			</aside>
			<main id="main" tabIndex={-1}>
				<div id="page">
					{status.has_overrides ? (
						<p className="warning" role="status">
							Saved dashboard overrides are active. <a href="#system">Manage overrides</a> or export the effective
							configuration.
						</p>
					) : null}

					<Suspense fallback={<p>Loading…</p>}>{page}</Suspense>
				</div>
			</main>
			<div id="announcement" className="sr-only" role="status" aria-live="polite">
				{serviceError || message}
			</div>
		</>
	);
}
