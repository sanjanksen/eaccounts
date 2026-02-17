import React from 'react';
import { View, Text, StyleSheet, FlatList } from 'react-native';
import { Theme } from '@/constants/theme';
import { ParsedTransaction } from '@/utils/finance';
import { TransactionItem } from './TransactionItem';

interface Props {
  transactions: ParsedTransaction[];
}

export function TransactionList({ transactions }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.sectionTitle}>Transactions</Text>
      <View style={styles.card}>
        {transactions.length === 0 ? (
          <Text style={styles.empty}>No transactions found</Text>
        ) : (
          <FlatList
            data={transactions}
            keyExtractor={(_, index) => index.toString()}
            renderItem={({ item }) => <TransactionItem transaction={item} />}
            ItemSeparatorComponent={() => <View style={styles.separator} />}
            scrollEnabled={false}
          />
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: Theme.spacing.md,
    paddingBottom: Theme.spacing.xl,
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
  separator: {
    height: 1,
    backgroundColor: Theme.colors.border,
    marginLeft: 44,
  },
  empty: {
    fontSize: Theme.fontSize.md,
    color: Theme.colors.textTertiary,
    textAlign: 'center',
    paddingVertical: Theme.spacing.lg,
  },
});
