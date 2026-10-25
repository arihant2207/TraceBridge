/**
 * Typed API client for TraceBridge backend.
 * Uses types generated from OpenAPI schema via openapi-typescript.
 */

import type { components, paths } from '../types/api';

export type AnalysisSummary = components['schemas']['AnalysisSummary'];
export type AnalysisDetail = components['schemas']['AnalysisDetail'];
export type FindingResponse = components['schemas']['FindingResponse'];
export type ReviewUpdateRequest = components['schemas']['ReviewUpdateRequest'];
export type ReviewResponse = components['schemas']['ReviewResponse'];
export type DatasetPreviewResponse = components['schemas']['DatasetPreviewResponse'];
export type DatasetInfo = components['schemas']['DatasetInfo'];
export type RequirementCoverageItem = components['schemas']['RequirementCoverageItem'];
export type TestOutcomeItem = components['schemas']['TestOutcomeItem'];

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: string[];
  };
}

export class ApiError extends Error {
  code: string;
  details: string[];
  status: number;

  constructor(status: number, code: string, message: string, details: string[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(
      0,
      'BACKEND_UNREACHABLE',
      'Backend server is unreachable. Please verify that the backend service is running on port 8000.',
      [err instanceof Error ? err.message : String(err)]
    );
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorCode = `HTTP_${res.status}`;
    let errorMessage = `Request failed with status ${res.status}`;
    let errorDetails: string[] = [];

    try {
      const data = await res.json();
      if (data && typeof data === 'object' && 'error' in data) {
        const envelope = data as ApiErrorEnvelope;
        errorCode = envelope.error.code || errorCode;
        errorMessage = envelope.error.message || errorMessage;
        errorDetails = Array.isArray(envelope.error.details) ? envelope.error.details : [];
      } else if (data && typeof data === 'object' && 'detail' in data) {
        // Fallback for standard FastAPI HTTPException details
        errorMessage = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // Body was not JSON
    }

    throw new ApiError(res.status, errorCode, errorMessage, errorDetails);
  }

  return res.json() as Promise<T>;
}

/**
 * List all analyses.
 */
export async function listAnalyses(): Promise<AnalysisSummary[]> {
  const res = await apiFetch('/api/v1/analyses', {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });
  return handleResponse<AnalysisSummary[]>(res);
}

/**
 * Get detailed analysis record by ID.
 */
export async function getAnalysis(id: string): Promise<AnalysisDetail> {
  const res = await apiFetch(`/api/v1/analyses/${encodeURIComponent(id)}`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });
  return handleResponse<AnalysisDetail>(res);
}

/**
 * Create analysis from sample dataset ('clean' or 'fault').
 */
export async function createAnalysisFromSample(sample: 'clean' | 'fault'): Promise<AnalysisDetail> {
  const res = await apiFetch(`/api/v1/analyses?sample=${encodeURIComponent(sample)}`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  });
  return handleResponse<AnalysisDetail>(res);
}

/**
 * Create analysis from uploaded multipart CSV files.
 */
export async function createAnalysisFromFiles(
  requirements: File,
  testResults: File,
  telemetry: File
): Promise<AnalysisDetail> {
  const formData = new FormData();
  formData.append('requirements', requirements, requirements.name);
  formData.append('test_results', testResults, testResults.name);
  formData.append('telemetry', telemetry, telemetry.name);

  const res = await apiFetch('/api/v1/analyses', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: formData,
  });
  return handleResponse<AnalysisDetail>(res);
}

export interface FindingFilters {
  severity?: string;
  rule_id?: string;
  class?: string;
  review_status?: string;
}

/**
 * Get findings for an analysis with optional filters.
 */
export async function getFindings(id: string, filters?: FindingFilters): Promise<FindingResponse[]> {
  const params = new URLSearchParams();
  if (filters?.severity && filters.severity !== 'all') {
    params.set('severity', filters.severity);
  }
  if (filters?.rule_id && filters.rule_id !== 'all') {
    params.set('rule_id', filters.rule_id);
  }
  if (filters?.class && filters.class !== 'all') {
    params.set('class', filters.class);
  }
  if (filters?.review_status && filters.review_status !== 'all') {
    params.set('review_status', filters.review_status);
  }

  const qs = params.toString() ? `?${params.toString()}` : '';
  const res = await apiFetch(`/api/v1/analyses/${encodeURIComponent(id)}/findings${qs}`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });
  return handleResponse<FindingResponse[]>(res);
}

/**
 * Get requirement coverage map for an analysis.
 */
export async function getCoverage(id: string): Promise<Record<string, RequirementCoverageItem>> {
  const res = await apiFetch(`/api/v1/analyses/${encodeURIComponent(id)}/coverage`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });
  return handleResponse<Record<string, RequirementCoverageItem>>(res);
}

/**
 * Preview raw parsed rows from a stored dataset.
 */
export async function getDatasetPreview(
  id: string,
  kind: string,
  limit = 20
): Promise<DatasetPreviewResponse> {
  const res = await apiFetch(
    `/api/v1/analyses/${encodeURIComponent(id)}/datasets/${encodeURIComponent(kind)}/preview?limit=${limit}`,
    {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    }
  );
  return handleResponse<DatasetPreviewResponse>(res);
}

/**
 * Update review status and reviewer note for a finding.
 */
export async function updateFindingReview(
  findingId: string,
  review: ReviewUpdateRequest
): Promise<ReviewResponse> {
  const res = await apiFetch(`/api/v1/findings/${encodeURIComponent(findingId)}/review`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(review),
  });
  return handleResponse<ReviewResponse>(res);
}

/**
 * URL for downloading sample zip files.
 */
export function getSampleZipUrl(sample: 'clean' | 'fault'): string {
  return `/api/v1/samples/${sample}.zip`;
}

/**
 * Get exported report content as plain text (Markdown, JSON, or CSV).
 */
export async function getExportText(id: string, format: 'md' | 'json' | 'csv' = 'md'): Promise<string> {
  const res = await apiFetch(`/api/v1/analyses/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`, {
    method: 'GET',
    headers: { Accept: '*/*' },
    cache: 'no-store',
  });
  if (!res.ok) {
    let errorCode = `HTTP_${res.status}`;
    let errorMessage = `Request failed with status ${res.status}`;
    let errorDetails: string[] = [];

    try {
      const data = await res.json();
      if (data && typeof data === 'object' && 'error' in data) {
        errorCode = data.error.code || errorCode;
        errorMessage = data.error.message || errorMessage;
        errorDetails = Array.isArray(data.error.details) ? data.error.details : [];
      }
    } catch {
      // not json
    }
    throw new ApiError(res.status, errorCode, errorMessage, errorDetails);
  }
  return res.text();
}

/**
 * URL for downloading export file directly.
 */
export function getExportDownloadUrl(id: string, format: 'md' | 'json' | 'csv'): string {
  return `/api/v1/analyses/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`;
}

