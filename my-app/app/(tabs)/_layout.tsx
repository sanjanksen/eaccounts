import { Tabs } from 'expo-router';
import React from 'react';
import { Ionicons } from '@expo/vector-icons';

import { HapticTab } from '@/components/haptic-tab';
import { DataProvider } from '@/contexts/DataContext';

export default function TabLayout() {
  return (
    <DataProvider>
      <Tabs
        screenOptions={{
          tabBarActiveTintColor: '#4ADE80',
          tabBarInactiveTintColor: '#64748B',
          headerShown: false,
          tabBarButton: HapticTab,
          tabBarStyle: {
            backgroundColor: '#141929',
            borderTopColor: '#1e2538',
            borderTopWidth: 1,
            height: 60,
            paddingBottom: 8,
            paddingTop: 8,
          },
          tabBarLabelStyle: {
            fontSize: 11,
            fontWeight: '600',
          },
        }}>
        <Tabs.Screen
          name="index"
          options={{
            title: 'Home',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name="home" size={size} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="explore"
          options={{
            title: 'Activity',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name="list" size={size} color={color} />
            ),
          }}
        />
        <Tabs.Screen
          name="budget"
          options={{
            title: 'Budget',
            tabBarIcon: ({ color, size }) => (
              <Ionicons name="pie-chart" size={size} color={color} />
            ),
          }}
        />
      </Tabs>
    </DataProvider>
  );
}
