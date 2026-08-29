/*
 * turret_uno_ver3.ino
 * P(degree) + U(microsecond) ????꾨줈?좎퐳
 *
 * P?꾨줈?좎퐳: P1<deg>T1<deg>P2<deg>T2<deg>L1<0/1>L2<0/1>  (?뺤닔, 1째?⑥쐞)
 * U?꾨줈?좎퐳: U<us>,<us>,<us>,<us>,<l1>,<l2>               (?뺤닔, ~0.1째?⑥쐞)
 */

#include <Servo.h>
#include <string.h>

Servo p1, t1, p2, t2;

const int L_PIN1 = 7;
const int L_PIN2 = 8;

char buffer[64];
char latest_buffer[64];
byte buffer_len = 0;
int v1, v2, v3, v4, l1_val, l2_val;

const int US_MIN = 544;
const int US_MAX = 2400;
const unsigned long COMMAND_TIMEOUT_MS = 300;
unsigned long last_command_ms = 0;

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(5);

  p1.attach(9);
  t1.attach(10);
  p2.attach(11);
  t2.attach(12);

  pinMode(L_PIN1, OUTPUT);
  pinMode(L_PIN2, OUTPUT);
  digitalWrite(L_PIN1, LOW);
  digitalWrite(L_PIN2, LOW);

  p1.writeMicroseconds(1472);  // 90째 以묒븰
  t1.writeMicroseconds(1472);
  p2.writeMicroseconds(1472);
  t2.writeMicroseconds(1472);

  delay(500);
}

bool isValidCommand(const char *cmd) {
  return cmd[0] == 'U' || cmd[0] == 'P';
}

void applyCommand(const char *cmd) {
  if (cmd[0] == 'U') {
    // ??U?꾨줈?좎퐳: microsecond (誘몄꽭 ?쒖뼱, ~0.1째 ?댁긽??
    // ?뺤떇: U<us>,<us>,<us>,<us>,<l1>,<l2>
    if (sscanf(cmd + 1, "%d,%d,%d,%d,%d,%d",
        &v1, &v2, &v3, &v4, &l1_val, &l2_val) == 6) {

      v1 = constrain(v1, US_MIN, US_MAX);
      v2 = constrain(v2, US_MIN, US_MAX);
      v3 = constrain(v3, US_MIN, US_MAX);
      v4 = constrain(v4, US_MIN, US_MAX);

      p1.writeMicroseconds(v1);
      t1.writeMicroseconds(v2);
      p2.writeMicroseconds(v3);
      t2.writeMicroseconds(v4);

      digitalWrite(L_PIN1, (l1_val == 1) ? HIGH : LOW);
      digitalWrite(L_PIN2, (l2_val == 1) ? HIGH : LOW);
      last_command_ms = millis();
    }
  }
  else if (cmd[0] == 'P') {
    // P?꾨줈?좎퐳: degree (湲곗〈 ?명솚)
    if (sscanf(cmd, "P1%dT1%dP2%dT2%dL1%dL2%d",
        &v1, &v2, &v3, &v4, &l1_val, &l2_val) == 6) {

      v1 = constrain(v1, 0, 180);
      v2 = constrain(v2, 0, 180);
      v3 = constrain(v3, 0, 180);
      v4 = constrain(v4, 0, 180);

      p1.write(v1);
      t1.write(v2);
      p2.write(v3);
      t2.write(v4);

      digitalWrite(L_PIN1, (l1_val == 1) ? HIGH : LOW);
      digitalWrite(L_PIN2, (l2_val == 1) ? HIGH : LOW);
      last_command_ms = millis();
    }
  }
}

void loop() {
  bool has_latest = false;

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      buffer[buffer_len] = '\0';
      if (buffer_len > 0 && isValidCommand(buffer)) {
        strncpy(latest_buffer, buffer, sizeof(latest_buffer) - 1);
        latest_buffer[sizeof(latest_buffer) - 1] = '\0';
        has_latest = true;
      }
      buffer_len = 0;
    }
    else if (buffer_len < sizeof(buffer) - 1) {
      buffer[buffer_len++] = c;
    }
    else {
      buffer_len = 0;
    }
  }

  if (has_latest) {
    applyCommand(latest_buffer);
  }

  if (last_command_ms > 0 && millis() - last_command_ms > COMMAND_TIMEOUT_MS) {
    digitalWrite(L_PIN1, LOW);
    digitalWrite(L_PIN2, LOW);
  }
}

/*
 * ==========================================
 * ?꾨줈?좎퐳 鍮꾧탳
 * ==========================================
 * P?꾨줈?좎퐳: 1째 ?⑥쐞, 湲곗〈 turret_server ?명솚
 * U?꾨줈?좎퐳: ~0.1째 ?⑥쐞 (1us ??0.097째)
 *   544us = 0째, 2400us = 180째
 *   1째 = 10.3us
 *
 * ? 諛곗튂 (蹂寃??놁쓬):
 * - 9: ?곕젢1 Pan, 10: ?곕젢1 Tilt
 * - 11: ?곕젢2 Pan, 12: ?곕젢2 Tilt
 * - 7: ?곕젢1 ?덉씠?, 8: ?곕젢2 ?덉씠?
 */
