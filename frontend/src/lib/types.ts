export type AuthProvider = "google" | "microsoft";

export type AuthSession = {
  authenticated: boolean;
  email?: string | null;
  name?: string | null;
  provider?: AuthProvider | null;
};

export type AuthProviderOption = {
  provider: AuthProvider;
  label: string;
};

export type OrderMetrics = {
  total: number;
  completed: number;
  needs_review: number;
  failed: number;
  unknown_supplier: number;
};

export type OrderListItem = {
  order_id: string;
  status: "COMPLETED" | "FAILED" | "NEEDS_REVIEW" | "UNKNOWN";
  supplier_code: string;
  supplier_name: string;
  invoice_number: string;
  sender: string;
  subject: string;
  filename: string;
  created_at?: string | null;
  line_items_count: number;
  warnings_count: number;
  is_test: boolean;
};

export type OrdersResponse = {
  items: OrderListItem[];
  metrics: OrderMetrics;
  total_items: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type OrderLineItem = {
  barcode: string;
  item_code: string;
  description: string;
  quantity: number;
  final_net_price: number;
};

export type OrderDetail = {
  order_id: string;
  status: "COMPLETED" | "FAILED" | "NEEDS_REVIEW" | "UNKNOWN";
  supplier_code: string;
  supplier_name: string;
  invoice_number: string;
  sender: string;
  subject: string;
  filename: string;
  created_at?: string | null;
  processing_cost_ils: number;
  is_test: boolean;
  warnings: string[];
  notes?: string | null;
  math_reasoning?: string | null;
  qty_reasoning?: string | null;
  line_items: OrderLineItem[];
  source_file_url: string;
  export_url: string;
};

export type Supplier = {
  code: string;
  name: string;
  global_id: string;
  email: string;
  phone: string;
  special_instructions: string;
};

export type SuppliersResponse = {
  items: Supplier[];
  total_items: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type Item = {
  barcode: string;
  name: string;
  item_code?: string | null;
  note?: string | null;
};

export type MutationResult = {
  success: boolean;
  count: number;
  message?: string | null;
};

export type UploadExtractionResult = {
  order_id: string;
  supplier_code: string;
  supplier_name: string;
  detection_method: string;
  new_items_added: number;
};
