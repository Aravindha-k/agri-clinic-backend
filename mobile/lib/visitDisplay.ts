import { VisitDetailDto, VisitDto } from '@/lib/api';

export function visitFarmerLabel(v: VisitDto | VisitDetailDto): string {
  const fi = 'farmer_info' in v ? v.farmer_info : null;
  if (fi?.name) return fi.name;
  if (v.farmer?.name) return v.farmer.name;
  if (v.farmer_name) return v.farmer_name;
  return 'Farmer';
}

export function visitVillageLabel(v: VisitDto | VisitDetailDto): string {
  if (v.village_name) return v.village_name;
  return '—';
}

export function visitCropLabel(v: VisitDto | VisitDetailDto): string {
  if ('crop_name' in v && v.crop_name) return v.crop_name;
  const ci = 'crop_info' in v ? v.crop_info : null;
  if (ci) {
    if (ci.name) return ci.name;
    const parts = [ci.name_en, ci.name_ta].filter(Boolean);
    if (parts.length) return parts.join(' / ');
  }
  if ('crop_name' in v && v.crop_name) return v.crop_name;
  return '—';
}

export function visitHasGps(v: VisitDto | VisitDetailDto): boolean {
  return (
    v.latitude != null &&
    v.longitude != null &&
    !Number.isNaN(Number(v.latitude)) &&
    !Number.isNaN(Number(v.longitude))
  );
}

export function normalizeVisitStatus(raw?: string | null): 'pending' | 'active' | 'completed' | 'other' {
  const s = (raw || '').toLowerCase();
  if (s === 'completed') return 'completed';
  if (s === 'active') return 'active';
  if (s === 'pending' || s === 'scheduled') return 'pending';
  return 'other';
}

export function formatVisitDateTime(v: VisitDto | VisitDetailDto): string {
  const d = v.visit_date || '';
  const t = v.visit_time || '';
  if (d && t) return `${d} · ${t}`;
  if (d) return d;
  return '—';
}
