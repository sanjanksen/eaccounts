import React from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Theme } from '@/constants/theme';
import { useData } from '@/contexts/DataContext';
import { BalanceSummary } from '@/components/BalanceSummary';
import { SpendingChart } from '@/components/SpendingChart';
import { TransactionItem } from '@/components/TransactionItem';

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const {
    transactions,
    totalBalance,
    weeklySpending,
    dailySpending,
    loading,
    refreshing,
    error,
    refresh,
  } = useData();

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
          <Pressable onPress={refresh}>
            <Text style={styles.retryButton}>Tap to retry</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  const recentTransactions = transactions.slice(0, 5);

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={refresh}
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

        <BalanceSummary totalBalance={totalBalance} weeklySpending={weeklySpending} />

        <SpendingChart data={dailySpending} />

        <View style={styles.recentHeader}>
          <Text style={styles.sectionTitle}>Recent</Text>
          <Pressable onPress={() => router.push('/explore')}>
            <Text style={styles.seeAll}>See all</Text>
          </Pressable>
        </View>
        <View style={styles.recentCard}>
          {recentTransactions.map((t, i) => (
            <React.Fragment key={i}>
              <TransactionItem transaction={t} />
              {i < recentTransactions.length - 1 && <View style={styles.separator} />}
            </React.Fragment>
          ))}
        </View>
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
  recentHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Theme.spacing.md,
    marginBottom: Theme.spacing.sm,
  },
  sectionTitle: {
    fontSize: Theme.fontSize.lg,
    fontWeight: '700',
    color: Theme.colors.text,
  },
  seeAll: {
    fontSize: Theme.fontSize.sm,
    fontWeight: '600',
    color: Theme.colors.primary,
  },
  recentCard: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.lg,
    padding: Theme.spacing.md,
    marginHorizontal: Theme.spacing.md,
  },
  separator: {
    height: 1,
    backgroundColor: Theme.colors.border,
    marginLeft: 44,
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
    backgroundColor: '#2e1a1a',
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
