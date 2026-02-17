import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Theme } from '@/constants/theme';
import { DailySpending } from '@/utils/finance';

interface Props {
  data: DailySpending[];
}

export function SpendingChart({ data }: Props) {
  const maxAmount = Math.max(...data.map((d) => d.amount), 1);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>This Week</Text>
      <View style={styles.chartRow}>
        {data.map((day, i) => {
          const height = day.amount > 0 ? (day.amount / maxAmount) * 120 : 4;
          return (
            <View key={i} style={styles.barColumn}>
              <View style={styles.barWrapper}>
                <View
                  style={[
                    styles.bar,
                    {
                      height,
                      backgroundColor: day.amount > 0 ? Theme.colors.chart : Theme.colors.border,
                    },
                  ]}
                />
              </View>
              <Text style={styles.barLabel}>{day.label}</Text>
              {day.amount > 0 && (
                <Text style={styles.barAmount}>${Math.round(day.amount)}</Text>
              )}
            </View>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: Theme.spacing.md,
    marginBottom: Theme.spacing.md,
    backgroundColor: Theme.colors.surface,
    borderRadius: Theme.radius.lg,
    padding: Theme.spacing.md,
  },
  title: {
    fontSize: Theme.fontSize.sm,
    fontWeight: '600',
    color: Theme.colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: Theme.spacing.md,
  },
  chartRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    height: 160,
  },
  barColumn: {
    flex: 1,
    alignItems: 'center',
  },
  barWrapper: {
    flex: 1,
    justifyContent: 'flex-end',
    width: '100%',
    alignItems: 'center',
  },
  bar: {
    width: 20,
    borderRadius: 6,
    minHeight: 4,
  },
  barLabel: {
    fontSize: 10,
    color: Theme.colors.textTertiary,
    marginTop: 6,
    fontWeight: '500',
  },
  barAmount: {
    fontSize: 9,
    color: Theme.colors.textSecondary,
    marginTop: 2,
  },
});
