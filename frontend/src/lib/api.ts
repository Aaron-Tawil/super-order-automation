import type {
  AuthProviderOption,
  AuthSession,
  Item,
  MutationResult,
  OrderDetail,
  OrdersResponse,
  Supplier,
  SuppliersResponse,
  UploadExtractionResult,
} from "@/lib/types";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with status ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  baseUrl: apiBaseUrl,
  getSession: () => request<AuthSession>("/api/v1/auth/session"),
  getProviders: () => request<AuthProviderOption[]>("/api/v1/auth/providers"),
  loginUrl: (provider: string, orderId?: string) =>
    `${apiBaseUrl}/api/v1/auth/login/${provider}${orderId ? `?order_id=${encodeURIComponent(orderId)}` : ""}`,
  logout: () =>
    request<MutationResult>("/api/v1/auth/logout", {
      method: "POST",
    }),
  getOrders: (params: URLSearchParams) => request<OrdersResponse>(`/api/v1/orders?${params.toString()}`),
  getOrder: (orderId: string) => request<OrderDetail>(`/api/v1/orders/${orderId}`),
  updateOrderTestFlag: (orderId: string, isTest: boolean) =>
    request<MutationResult>(`/api/v1/orders/${orderId}/test-flag`, {
      method: "POST",
      body: JSON.stringify({ is_test: isTest }),
    }),
  extractUpload: (formData: FormData) =>
    request<UploadExtractionResult>("/api/v1/uploads/extract", {
      method: "POST",
      body: formData,
    }),
  getSuppliers: (params: URLSearchParams) => request<SuppliersResponse>(`/api/v1/suppliers?${params.toString()}`),
  createSupplier: (payload: Partial<Supplier>) =>
    request<MutationResult>("/api/v1/suppliers", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateSupplier: (code: string, payload: Partial<Supplier>) =>
    request<MutationResult>(`/api/v1/suppliers/${code}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  searchItems: (query: string) => request<Item[]>(`/api/v1/items/search?query=${encodeURIComponent(query)}`),
  createItem: (payload: Item) =>
    request<MutationResult>("/api/v1/items", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createItemsBatch: (items: Item[]) =>
    request<MutationResult>("/api/v1/items/batch", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),
  deleteItems: (barcodes: string[]) =>
    request<MutationResult>("/api/v1/items/delete-batch", {
      method: "POST",
      body: JSON.stringify({ barcodes }),
    }),
};
