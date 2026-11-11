import { useRecordings } from '../queries';
import { ErrorText, PageTitle, Panel } from '../components/common';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

export default function Recordings() {
	const { data: recordings, error } = useRecordings();
	return (
		<>
			<PageTitle>Recordings</PageTitle>
			<ErrorText error={error} />
			<Panel>
				{recordings?.length ? (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Name</TableHead>
								<TableHead className="text-right">Size</TableHead>
								<TableHead>Finished</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{recordings.map((r) => (
								<TableRow key={r.name}>
									<TableCell>
										<a href={'/recordings/' + encodeURIComponent(r.name)} download>
											{r.name}
										</a>
									</TableCell>
									<TableCell className="text-right">{(r.bytes / 1e6).toFixed(1)} MB</TableCell>
									<TableCell>{new Date(r.modified * 1000).toLocaleString()}</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				) : (
					<p className="text-sm text-muted-foreground">
						{recordings ? 'No recordings yet. Spot records matches and robot enables.' : 'Loading…'}
					</p>
				)}
			</Panel>
		</>
	);
}
