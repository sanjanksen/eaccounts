import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Theme } from '@/constants/theme';

interface Props {
  budget: number;
  spent: number;
}

export function BudgetCard({ budget, spent }: Props) {
  const progress = budget > 0 ? Math.min(spent / budget, 1) : 0;
  const overBudget = spent > budget && budget > 0;
  const remaining = Math.max(budget - spent, 0);

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Weekly Budget</Text>
        <Text style={[styles.status, overBudget ? styles.statusOver : styles.statusUnder]}>
          {overBudget ? 'Over budget' : 'On track'}
        </Text>
      </View>

      <View style={styles.amountsRow}>
        <View>
          <Text style={styles.amountLabel}>Spent</Text>
          <Text style={[styles.amount, overBudget && styles.amountOver]}>
            ${spent.toFixed(2)}
          </Text>
        </View>
        <View style={styles.amountRight}>
          <Text style={styles.amountLabel}>Remaining</Text>
          <Text style={styles.amount}>${remaining.toFixed(2)}</Text>
        </View>
      </View>

      <View style={styles.trackOuter}>
        <View
          style={[
            styles.trackInner,
            {
              width: `${progress * 100}%`,
              backgroundColor: overBudget ? Theme.colors.danger : Theme.colors.success,
            },
          ]}
        />
      </View>

      <Text style={styles.budgetText}>
        ${spent.toFixed(2)} of ${budget.toFixed(2)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.lg,
    padding: Theme.spacing.md,
    marginHorizontal: Theme.spacing.md,
    marginBottom: Theme.spacing.md,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: Theme.spacing.md,
  },
  title: {
    fontSize: Theme.fontSize.lg,
    fontWeight: '700',
    color: Theme.colors.text,
  },
  status: {
    fontSize: Theme.fontSize.xs,
    fontWeight: '600',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    overflow: 'hidden',
  },
  statusUnder: {
    color: Theme.colors.success,
    backgroundColor: '#1a2e1f',
  },
  statusOver: {
    color: Theme.colors.danger,
    backgroundColor: '#2e1a1a',
  },
  amountsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: Theme.spacing.md,
  },
  amountRight: {
    alignItems: 'flex-end',
  },
  amountLabel: {
    fontSize: Theme.fontSize.xs,
    color: Theme.colors.textTertiary,
    marginBottom: 2,
  },
  amount: {
    fontSize: Theme.fontSize.xl,
    fontWeight: '700',
    color: Theme.colors.text,
  },
  amountOver: {
    color: Theme.colors.danger,
  },
  trackOuter: {
    height: 8,
    backgroundColor: Theme.colors.border,
    borderRadius: 4,
    overflow: 'hidden',
    marginBottom: Theme.spacing.sm,
  },
  trackInner: {
    height: '100%',
    borderRadius: 4,
  },
  budgetText: {
    fontSize: Theme.fontSize.xs,
    color: Theme.colors.textTertiary,
    textAlign: 'center',
  },
});
