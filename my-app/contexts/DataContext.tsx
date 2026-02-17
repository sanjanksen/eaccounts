import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
  ParsedAccount,
  ParsedTransaction,
  DailySpending,
  parseAccounts,
  parseTransactions,
  calculateTotalBalance,
  calculateWeeklySpending,
  getDailySpending,
} from '@/utils/finance';

const BASE_URL = 'https://eaccounts-production.up.railway.app';

interface DataContextType {
  accounts: ParsedAccount[];
  transactions: ParsedTransaction[];
  totalBalance: number;
  weeklySpending: number;
  dailySpending: DailySpending[];
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  refresh: () => void;
}

const DataContext = createContext<DataContextType>({
  accounts: [],
  transactions: [],
  totalBalance: 0,
  weeklySpending: 0,
  dailySpending: [],
  loading: true,
  refreshing: false,
  error: null,
  refresh: () => {},
});

export function useData() {
  return useContext(DataContext);
}

export function DataProvider({ children }: { children: React.ReactNode }) {
  const [accounts, setAccounts] = useState<ParsedAccount[]>([]);
  const [transactions, setTransactions] = useState<ParsedTransaction[]>([]);
  const [totalBalance, setTotalBalance] = useState(0);
  const [weeklySpending, setWeeklySpending] = useState(0);
  const [dailySpending, setDailySpending] = useState<DailySpending[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);

      const [balanceRes, transactionsRes] = await Promise.all([
        fetch(`${BASE_URL}/api/balance`),
        fetch(`${BASE_URL}/api/transactions`),
      ]);

      const balanceData = await balanceRes.json();
      const transactionsData = await transactionsRes.json();

      if (balanceData.error) {
        setError(balanceData.error);
        return;
      }
      if (transactionsData.error) {
        setError(transactionsData.error);
        return;
      }

      const parsedAccounts = parseAccounts(balanceData.accounts || []);
      const parsedTransactions = parseTransactions(transactionsData.transactions || []);

      setAccounts(parsedAccounts);
      setTransactions(parsedTransactions);
      setTotalBalance(calculateTotalBalance(parsedAccounts));
      setWeeklySpending(calculateWeeklySpending(parsedTransactions));
      setDailySpending(getDailySpending(parsedTransactions));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const refresh = useCallback(() => {
    setRefreshing(true);
    fetchData();
  }, [fetchData]);

  return (
    <DataContext.Provider
      value={{
        accounts,
        transactions,
        totalBalance,
        weeklySpending,
        dailySpending,
        loading,
        refreshing,
        error,
        refresh,
      }}
    >
      {children}
    </DataContext.Provider>
  );
}
