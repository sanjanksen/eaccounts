import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Theme } from '@/constants/theme';
import { ParsedTransaction } from '@/utils/finance';

interface Props {
  transaction: ParsedTransaction;
}

function formatDate(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) {
    return 'Today';
  } else if (diffDays === 1) {
    return 'Yesterday';
  } else if (diffDays < 7) {
    return `${diffDays}d ago`;
  }
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function cleanLocation(location: string): string {
  // Shorten long location names
  const parts = location.split(' ');
  if (parts.length > 4) {
    return parts.slice(0, 4).join(' ');
  }
  return location;
}

export function TransactionItem({ transaction }: Props) {
  const isDebit = transaction.amount < 0;

  return (
    <View style={styles.row}>
      <View style={[styles.icon, isDebit ? styles.iconDebit : styles.iconCredit]}>
        <Text style={[styles.iconText, isDebit ? styles.iconTextDebit : styles.iconTextCredit]}>
          {isDebit ? '-' : '+'}
        </Text>
      </View>
      <View style={styles.details}>
        <Text style={styles.location} numberOfLines={1}>
          {cleanLocation(transaction.location)}
        </Text>
        <Text style={styles.meta}>
          {transaction.account} · {formatDate(transaction.date)}
        </Text>
      </View>
      <Text style={[styles.amount, isDebit ? styles.amountDebit : styles.amountCredit]}>
        {isDebit ? '-' : '+'}$
        {Math.abs(transaction.amount).toLocaleString('en-US', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
  },
  icon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Theme.spacing.sm,
  },
  iconDebit: {
    backgroundColor: '#FEE2E2',
  },
  iconCredit: {
    backgroundColor: '#D1FAE5',
  },
  iconText: {
    fontSize: Theme.fontSize.lg,
    fontWeight: '700',
  },
  iconTextDebit: {
    color: Theme.colors.danger,
  },
  iconTextCredit: {
    color: Theme.colors.success,
  },
  details: {
    flex: 1,
  },
  location: {
    fontSize: Theme.fontSize.md,
    fontWeight: '500',
    color: Theme.colors.text,
  },
  meta: {
    fontSize: Theme.fontSize.xs,
    color: Theme.colors.textTertiary,
    marginTop: 2,
  },
  amount: {
    fontSize: Theme.fontSize.md,
    fontWeight: '600',
  },
  amountDebit: {
    color: Theme.colors.danger,
  },
  amountCredit: {
    color: Theme.colors.success,
  },
});
