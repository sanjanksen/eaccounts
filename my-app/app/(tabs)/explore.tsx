import React from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Theme } from '@/constants/theme';
import { useData } from '@/contexts/DataContext';
import { AccountList } from '@/components/AccountList';
import { TransactionItem } from '@/components/TransactionItem';

export default function ActivityScreen() {
  const insets = useSafeAreaInsets();
  const { accounts, transactions, loading, refreshing, error, refresh } = useData();

  if (loading) {
    return (
      <View style={[styles.centered, { paddingTop: insets.top }]}>
        <ActivityIndicator size="large" color={Theme.colors.primary} />
      </View>
    );
  }

  if (error) {
    return (
      <View style={[styles.centered, { paddingTop: insets.top }]}>
        <Text style={styles.errorText}>{error}</Text>
      </View>
    );
  }

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <FlatList
        data={transactions}
        keyExtractor={(_, index) => index.toString()}
        renderItem={({ item }) => (
          <View style={styles.itemWrapper}>
            <TransactionItem transaction={item} />
          </View>
        )}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        ListHeaderComponent={
          <View>
            <View style={styles.header}>
              <Text style={styles.title}>Activity</Text>
            </View>
            <AccountList accounts={accounts} />
            <Text style={styles.sectionTitle}>All Transactions</Text>
            <View style={styles.listCardTop} />
          </View>
        }
        ListFooterComponent={<View style={styles.listCardBottom} />}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={refresh}
            tintColor={Theme.colors.primary}
          />
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Theme.colors.background,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: Theme.colors.background,
  },
  errorText: {
    color: Theme.colors.danger,
    fontSize: Theme.fontSize.md,
  },
  header: {
    paddingHorizontal: Theme.spacing.md,
    paddingTop: Theme.spacing.md,
    paddingBottom: Theme.spacing.md,
  },
  title: {
    fontSize: Theme.fontSize.xxl,
    fontWeight: '800',
    color: Theme.colors.text,
  },
  sectionTitle: {
    fontSize: Theme.fontSize.lg,
    fontWeight: '700',
    color: Theme.colors.text,
    paddingHorizontal: Theme.spacing.md,
    marginBottom: Theme.spacing.sm,
  },
  listCardTop: {
    backgroundColor: Theme.colors.surface,
    borderTopLeftRadius: Theme.radius.lg,
    borderTopRightRadius: Theme.radius.lg,
    height: 4,
    marginHorizontal: Theme.spacing.md,
  },
  listCardBottom: {
    backgroundColor: Theme.colors.surface,
    borderBottomLeftRadius: Theme.radius.lg,
    borderBottomRightRadius: Theme.radius.lg,
    height: 16,
    marginHorizontal: Theme.spacing.md,
    marginBottom: 40,
  },
  itemWrapper: {
    backgroundColor: Theme.colors.surface,
    paddingHorizontal: Theme.spacing.md,
    marginHorizontal: Theme.spacing.md,
  },
  separator: {
    height: 1,
    backgroundColor: Theme.colors.border,
    marginLeft: 60,
    marginRight: Theme.spacing.md,
    marginHorizontal: Theme.spacing.md,
  },
  listContent: {
    paddingBottom: 20,
  },
});
