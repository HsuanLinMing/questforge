import 'package:flutter_test/flutter_test.dart';
import 'package:questforge_flutter_demo/main.dart';

void main() {
  testWidgets('App builds', (tester) async {
    await tester.pumpWidget(const QuestForgeDemoApp());
    expect(find.text('QuestForge Day20-C Demo'), findsOneWidget);
  });
}
