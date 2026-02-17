import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Theme } from '@/constants/theme';
import { ParsedAccount } from '@/utils/finance';

interface Props {
  accounts: ParsedAccount[];
}

export function AccountList({ accounts }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.sectionTitle}>Accounts</Text>
      <View style={styles.card}>
        {accounts.map((account, index) => (
          <View key={account.name}>
            <View style={styles.row}>
              <View style={styles.iconCircle}>
                <Text style={styles.iconText}>{account.name.charAt(0)}</Text>
              </View>
              <Text style={styles.accountName} numberOfLines={1}>
                {account.name}
              </Text>
              <Text
                style={[
                  styles.accountBalance,
                  account.balance === null && styles.accountBadge,
                ]}
              >
                {account.balance !== null
                  ? `$${account.balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                  : account.rawBalance}
              </Text>
            </View>
            {index < accounts.length - 1 && <View style={styles.separator} />}
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: Theme.spacing.md,
    paddingBottom: Theme.spacing.md,
  },
  sectionTitle: {
    fontSize: Theme.fontSize.lg,
    fontWeight: '700',
    color: Theme.colors.text,
    marginBottom: Theme.spacing.sm,
  },
  card: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.lg,
    padding: Theme.spacing.md,
    ...Theme.shadow.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: Theme.spacing.sm,
  },
  iconCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: Theme.colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Theme.spacing.sm,
  },
  iconText: {
    fontSize: Theme.fontSize.sm,
    fontWeight: '700',
    color: Theme.colors.primary,
  },
  accountName: {
    flex: 1,
    fontSize: Theme.fontSize.md,
    color: Theme.colors.text,
    fontWeight: '500',
  },
  accountBalance: {
    fontSize: Theme.fontSize.md,
    fontWeight: '600',
    color: Theme.colors.text,
  },
  accountBadge: {
    color: Theme.colors.success,
    fontSize: Theme.fontSize.sm,
    fontWeight: '600',
  },
  separator: {
    height: 1,
    backgroundColor: Theme.colors.border,
    marginLeft: 44,
  },
});
