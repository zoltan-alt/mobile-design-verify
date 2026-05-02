// Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

import 'package:flutter/material.dart';

void main() {
  runApp(const TodoVerifyApp());
}

class TodoVerifyApp extends StatelessWidget {
  const TodoVerifyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'todo-verify',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}

class TodoItem {
  const TodoItem(this.title, this.steps);
  final String title;
  final List<String> steps;
}

const _todos = <TodoItem>[
  TodoItem('Buy groceries', [
    'Make a list',
    'Drive to the store',
    'Bring reusable bags',
  ]),
  TodoItem('Reply to emails', [
    'Triage the inbox',
    'Reply to anything urgent',
    'Archive the rest',
  ]),
  TodoItem('Read a book', [
    'Pick a book from the shelf',
    'Find a quiet spot',
    'Read for 30 minutes',
  ]),
];

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Todos')),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: _todos.length,
        itemBuilder: (context, index) {
          final todo = _todos[index];
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Semantics(
              identifier: 'todo-card-$index',
              child: Card(
                child: ListTile(
                  title: Text(todo.title),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () {
                    Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => DetailScreen(index: index, todo: todo),
                      ),
                    );
                  },
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class DetailScreen extends StatelessWidget {
  const DetailScreen({super.key, required this.index, required this.todo});

  final int index;
  final TodoItem todo;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Semantics(
          identifier: 'todo-detail-$index',
          child: Text(todo.title),
        ),
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: todo.steps.length,
        itemBuilder: (context, stepIndex) {
          return Semantics(
            identifier: 'todo-step-row-$stepIndex',
            child: ListTile(
              leading: Text('${stepIndex + 1}.'),
              title: Text(todo.steps[stepIndex]),
            ),
          );
        },
      ),
    );
  }
}
