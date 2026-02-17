import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Theme } from '@/constants/theme';

interface Props {
  totalBalance: number;
  weeklySpending: number;
}

export function BalanceSummary({ totalBalance, weeklySpending }: Props) {
  return (
    <View style={styles.container}>
      <View style={styles.heroCard}>
        <Text style={styles.label}>Total Balance</Text>
        <Text style={styles.balance}>
          ${totalBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </Text>
        <View style={styles.divider} />
        <View style={styles.spentRow}>
          <View style={styles.spentDot} />
          <Text style={styles.spentLabel}>Spent this week</Text>
          <Text style={styles.spentAmount}>
            ${weeklySpending.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: Theme.spacing.md,
    paddingTop: Theme.spacing.sm,
    paddingBottom: Theme.spacing.md,
  },
  heroCard: {
    backgroundColor: Theme.colors.primary,
    borderRadius: Theme.radius.xl,
    padding: Theme.spacing.lg,
    ...Theme.shadow.lg,
  },
  label: {
    fontSize: Theme.fontSize.sm,
    color: 'rgba(255,255,255,0.7)',
    fontWeight: '500',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  balance: {
    fontSize: Theme.fontSize.hero,
    color: '#FFFFFF',
    fontWeight: '700',
    marginTop: Theme.spacing.xs,
    letterSpacing: -1,
  },
  divider: {
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.15)',
    marginVertical: Theme.spacing.md,
  },
  spentRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  spentDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: Theme.colors.spent,
    marginRight: Theme.spacing.sm,
  },
  spentLabel: {
    fontSize: Theme.fontSize.sm,
    color: 'rgba(255,255,255,0.7)',
    flex: 1,
  },
  spentAmount: {
    fontSize: Theme.fontSize.lg,
    color: '#FFFFFF',
    fontWeight: '600',
  },
});
