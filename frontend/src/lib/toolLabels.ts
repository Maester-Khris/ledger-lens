export const TOOL_LABEL: Record<string, string> = {
  compare_contract_to_billing: 'Billing reconciliation',
  get_contract_fields: 'Contract terms lookup',
};

export function toolLabel(name: string): string {
  return TOOL_LABEL[name] ?? name;
}
