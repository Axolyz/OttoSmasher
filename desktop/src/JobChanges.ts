export function completedFor(event: Event, target: {sample?: string; source?: string}, operations: string[]) {
  const jobs: any[] = (event as CustomEvent).detail || [];
  return jobs.some(j => j.status === "succeeded" && operations.includes(j.operation) && (
    (!target.sample && !target.source) ||
    (target.sample && (j.affected?.sample_ids?.includes(target.sample) || j.payload?.material_id === target.sample || j.payload?.material_ids?.includes(target.sample) || j.payload?.ids?.includes(target.sample) || j.result?.rows?.some((r: any) => r.material_id === target.sample))) ||
    (target.source && (j.affected?.source_ids?.includes(target.source) || j.payload?.source_id === target.source || j.payload?.source_ids?.includes(target.source)))
  ));
}
