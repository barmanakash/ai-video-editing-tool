// Thin wrapper around the local FastAPI backend (proxied at /api by Vite).
const BASE = '/api';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function detailText(data) {
  if (!data) return '';
  const d = data.detail ?? data;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d.map((e) => `${(e.loc || []).slice(1).join('.') || 'field'}: ${e.msg}`).join('; ');
  }
  return JSON.stringify(d);
}

async function request(path, { method = 'GET', json, form } = {}) {
  const opts = { method, headers: {} };
  if (json !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  let res;
  try {
    res = await fetch(BASE + path, opts);
  } catch {
    throw new ApiError('Cannot reach the backend. Start it with: uvicorn app.main:app --host 127.0.0.1 --port 8000', 0);
  }
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(detailText(data) || res.statusText, res.status);
  return data;
}

const q = (params) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));
  const str = s.toString();
  return str ? `?${str}` : '';
};

export const api = {
  health: () => request('/health'),
  exportOptions: () => request('/export/options'),
  estimateExport: (body) => request('/export/estimate', { method: 'POST', json: body }),

  // videos
  listVideos: () => request('/videos'),
  registerVideo: (path, role) => request('/videos/register', { method: 'POST', json: { path, role } }),
  uploadVideo: (file, role) => {
    const form = new FormData();
    form.append('file', file);
    form.append('role', role);
    return request('/videos/upload', { method: 'POST', form });
  },
  deleteVideo: (id) => request(`/videos/${id}`, { method: 'DELETE' }),

  // analysis
  analyzeGameplay: (id, force = false) => request(`/gameplay/${id}/analyze${q({ force })}`, { method: 'POST' }),
  gameplayAnalyses: () => request('/gameplay/analyses'),
  analyzeReference: (id, force = false) => request(`/reference/${id}/analyze${q({ force })}`, { method: 'POST' }),
  referenceProfiles: () => request('/reference/profiles'),

  // plans
  generatePlan: (body) => request('/plans/generate', { method: 'POST', json: body }),
  listPlans: () => request('/plans'),
  getPlan: (id) => request(`/plans/${id}`),
  savePlan: (id, plan) => request(`/plans/${id}`, { method: 'PUT', json: plan }),
  deletePlan: (id, deleteOutput) => request(`/plans/${id}${q({ delete_output: deleteOutput })}`, { method: 'DELETE' }),

  // rendering
  startRender: (id, overrides) =>
    request(`/plans/${id}/render`, { method: 'POST', ...(overrides ? { json: overrides } : {}) }),
  renderStatus: (id) => request(`/plans/${id}/render`),
  cancelRender: (id) => request(`/plans/${id}/render/cancel`, { method: 'POST' }),
  outputUrl: (id, stamp) => `${BASE}/plans/${id}/output${stamp ? `?t=${encodeURIComponent(stamp)}` : ''}`,
  thumbnailUrl: (path) => `${BASE}${path}`,
};
