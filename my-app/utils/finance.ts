export interface Account {
  name: string;
  balance: string;
}

export interface ParsedAccount {
  name: string;
  balance: number | null;
  rawBalance: string;
}

export interface Transaction {
  account: string;
  amount: string;
  date: string;
  location: string;
  type: string;
}

export interface ParsedTransaction {
  account: string;
  amount: number;
  date: Date;
  dateString: string;
  location: string;
  type: string;
}

/**
 * Parse a currency string like "559.72 USD" into a number.
 * Returns null for non-numeric balances like "Active".
 */
export function parseCurrency(value: string): number | null {
  const match = value.match(/^([\d,]+\.?\d*)\s+\w+$/);
  if (!match) return null;
  return parseFloat(match[1].replace(/,/g, ''));
}

/**
 * Parse a transaction amount like "(12.89) USD" into a signed number.
 * Parenthesized amounts are negative (debits).
 */
export function parseTransactionAmount(value: string): number {
  const debitMatch = value.match(/^\(([\d,]+\.?\d*)\)\s+\w+$/);
  if (debitMatch) {
    return -parseFloat(debitMatch[1].replace(/,/g, ''));
  }
  const creditMatch = value.match(/^([\d,]+\.?\d*)\s+\w+$/);
  if (creditMatch) {
    return parseFloat(creditMatch[1].replace(/,/g, ''));
  }
  return 0;
}

/**
 * Parse a date string like "2/14/2026 3:42 PM" into a Date object.
 */
export function parseDate(dateStr: string): Date {
  return new Date(dateStr);
}

/**
 * Calculate total money spent (debits) in the last 7 days.
 */
export function calculateWeeklySpending(transactions: ParsedTransaction[]): number {
  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

  return transactions.reduce((total, t) => {
    if (t.amount < 0 && t.date >= weekAgo) {
      return total + Math.abs(t.amount);
    }
    return total;
  }, 0);
}

/**
 * Parse raw accounts into structured data.
 */
export function parseAccounts(accounts: Account[]): ParsedAccount[] {
  return accounts.map((a) => ({
    name: a.name,
    balance: parseCurrency(a.balance),
    rawBalance: a.balance,
  }));
}

/**
 * Parse raw transactions into structured data, sorted by date descending.
 */
export function parseTransactions(transactions: Transaction[]): ParsedTransaction[] {
  return transactions
    .map((t) => ({
      account: t.account,
      amount: parseTransactionAmount(t.amount),
      date: parseDate(t.date),
      dateString: t.date,
      location: t.location,
      type: t.type,
    }))
    .sort((a, b) => b.date.getTime() - a.date.getTime());
}

/**
 * Calculate total balance from numeric accounts only.
 */
export function calculateTotalBalance(accounts: ParsedAccount[]): number {
  return accounts.reduce((total, a) => {
    if (a.balance !== null) {
      return total + a.balance;
    }
    return total;
  }, 0);
}
