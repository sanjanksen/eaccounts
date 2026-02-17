import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Theme } from '@/constants/theme';
import {
  ParsedAccount,
  ParsedTransaction,
  parseAccounts,
  parseTransactions,
  calculateTotalBalance,
  calculateWeeklySpending,
} from '@/utils/finance';
import { BalanceSummary } from '@/components/BalanceSummary';
import { AccountList } from '@/components/AccountList';
import { TransactionList } from '@/components/TransactionList';

const BASE_URL = 'https://eaccounts-production.up.railway.app';

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const [accounts, setAccounts] = useState<ParsedAccount[]>([]);
  const [transactions, setTransactions] = useState<ParsedTransaction[]>([]);
  const [totalBalance, setTotalBalance] = useState(0);
  const [weeklySpending, setWeeklySpending] = useState(0);
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

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <View style={[styles.centered, { paddingTop: insets.top }]}>
        <ActivityIndicator size="large" color={Theme.colors.primary} />
        <Text style={styles.loadingText}>Loading your accounts...</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={[styles.centered, { paddingTop: insets.top }]}>
        <View style={styles.errorCard}>
          <Text style={styles.errorIcon}>!</Text>
          <Text style={styles.errorTitle}>Unable to Load</Text>
          <Text style={styles.errorMessage}>{error}</Text>
          <Text style={styles.retryButton} onPress={fetchData}>
            Tap to retry
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <StatusBar style="dark" />
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={Theme.colors.primary}
          />
        }
      >
        <View style={styles.header}>
          <Text style={styles.greeting}>eAccounts</Text>
          <Text style={styles.date}>
            {new Date().toLocaleDateString('en-US', {
              weekday: 'long',
              month: 'long',
              day: 'numeric',
            })}
          </Text>
        </View>

        <BalanceSummary
          totalBalance={totalBalance}
          weeklySpending={weeklySpending}
        />

        <AccountList accounts={accounts} />

        <TransactionList transactions={transactions} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Theme.colors.background,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 40,
  },
  header: {
    paddingHorizontal: Theme.spacing.md,
    paddingTop: Theme.spacing.md,
    paddingBottom: Theme.spacing.sm,
  },
  greeting: {
    fontSize: Theme.fontSize.xxl,
    fontWeight: '800',
    color: Theme.colors.text,
    letterSpacing: -0.5,
  },
  date: {
    fontSize: Theme.fontSize.sm,
    color: Theme.colors.textSecondary,
    marginTop: 2,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: Theme.colors.background,
    padding: Theme.spacing.xl,
  },
  loadingText: {
    marginTop: Theme.spacing.md,
    fontSize: Theme.fontSize.md,
    color: Theme.colors.textSecondary,
  },
  errorCard: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.xl,
    padding: Theme.spacing.xl,
    alignItems: 'center',
    ...Theme.shadow.md,
    width: '100%',
    maxWidth: 320,
  },
  errorIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#FEE2E2',
    color: Theme.colors.danger,
    fontSize: Theme.fontSize.xl,
    fontWeight: '700',
    textAlign: 'center',
    lineHeight: 48,
    overflow: 'hidden',
    marginBottom: Theme.spacing.md,
  },
  errorTitle: {
    fontSize: Theme.fontSize.lg,
    fontWeight: '700',
    color: Theme.colors.text,
    marginBottom: Theme.spacing.sm,
  },
  errorMessage: {
    fontSize: Theme.fontSize.sm,
    color: Theme.colors.textSecondary,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: Theme.spacing.md,
  },
  retryButton: {
    fontSize: Theme.fontSize.md,
    fontWeight: '600',
    color: Theme.colors.primary,
    paddingVertical: Theme.spacing.sm,
    paddingHorizontal: Theme.spacing.md,
  },
});
