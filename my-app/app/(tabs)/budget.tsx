import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  ScrollView,
  Pressable,
  Keyboard,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Theme } from '@/constants/theme';
import { useData } from '@/contexts/DataContext';
import { BudgetCard } from '@/components/BudgetCard';
import { SpendingChart } from '@/components/SpendingChart';

const BUDGET_KEY = 'weekly_budget';

export default function BudgetScreen() {
  const insets = useSafeAreaInsets();
  const { weeklySpending, dailySpending } = useData();
  const [budget, setBudget] = useState(0);
  const [inputValue, setInputValue] = useState('');
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(BUDGET_KEY).then((val) => {
      if (val) {
        const num = parseFloat(val);
        setBudget(num);
        setInputValue(num.toString());
      }
    });
  }, []);

  const saveBudget = async () => {
    Keyboard.dismiss();
    const num = parseFloat(inputValue);
    if (!isNaN(num) && num > 0) {
      setBudget(num);
      await AsyncStorage.setItem(BUDGET_KEY, num.toString());
      setEditing(false);
    }
  };

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.header}>
          <Text style={styles.title}>Budget</Text>
        </View>

        {budget > 0 ? (
          <BudgetCard budget={budget} spent={weeklySpending} />
        ) : (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyTitle}>No budget set</Text>
            <Text style={styles.emptySubtitle}>
              Set a weekly spending limit to track your progress
            </Text>
          </View>
        )}

        <View style={styles.inputCard}>
          <Text style={styles.inputLabel}>
            {budget > 0 ? 'Update weekly budget' : 'Set weekly budget'}
          </Text>
          <View style={styles.inputRow}>
            <Text style={styles.dollar}>$</Text>
            <TextInput
              style={styles.input}
              value={inputValue}
              onChangeText={(text) => {
                setInputValue(text);
                setEditing(true);
              }}
              keyboardType="decimal-pad"
              placeholder="0.00"
              placeholderTextColor={Theme.colors.textTertiary}
            />
            <Pressable
              style={[styles.saveButton, !editing && styles.saveButtonDisabled]}
              onPress={saveBudget}
              disabled={!editing}
            >
              <Text style={[styles.saveText, !editing && styles.saveTextDisabled]}>
                Save
              </Text>
            </Pressable>
          </View>
        </View>

        <SpendingChart data={dailySpending} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Theme.colors.background,
  },
  content: {
    paddingBottom: 40,
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
  emptyCard: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.lg,
    padding: Theme.spacing.xl,
    marginHorizontal: Theme.spacing.md,
    marginBottom: Theme.spacing.md,
    alignItems: 'center',
  },
  emptyTitle: {
    fontSize: Theme.fontSize.lg,
    fontWeight: '700',
    color: Theme.colors.text,
    marginBottom: Theme.spacing.xs,
  },
  emptySubtitle: {
    fontSize: Theme.fontSize.sm,
    color: Theme.colors.textSecondary,
    textAlign: 'center',
  },
  inputCard: {
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.lg,
    padding: Theme.spacing.md,
    marginHorizontal: Theme.spacing.md,
    marginBottom: Theme.spacing.md,
  },
  inputLabel: {
    fontSize: Theme.fontSize.sm,
    fontWeight: '600',
    color: Theme.colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: Theme.spacing.sm,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  dollar: {
    fontSize: Theme.fontSize.xl,
    fontWeight: '700',
    color: Theme.colors.textSecondary,
    marginRight: 4,
  },
  input: {
    flex: 1,
    fontSize: Theme.fontSize.xl,
    fontWeight: '700',
    color: Theme.colors.text,
    paddingVertical: Theme.spacing.sm,
  },
  saveButton: {
    backgroundColor: Theme.colors.primary,
    paddingHorizontal: Theme.spacing.md,
    paddingVertical: Theme.spacing.sm,
    borderRadius: Theme.radius.sm,
  },
  saveButtonDisabled: {
    backgroundColor: Theme.colors.border,
  },
  saveText: {
    fontSize: Theme.fontSize.md,
    fontWeight: '700',
    color: '#0B0F1A',
  },
  saveTextDisabled: {
    color: Theme.colors.textTertiary,
  },
});
