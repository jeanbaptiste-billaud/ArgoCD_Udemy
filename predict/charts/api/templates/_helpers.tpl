{{- define "api.labels" -}}
app.kubernetes.io/name: {{ .Values.name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: api
app.kubernetes.io/part-of: predict
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
predict/environment: {{ required "global.environment est obligatoire" .Values.global.environment }}
{{- end }}

{{- define "api.selectorLabels" -}}
app.kubernetes.io/name: {{ .Values.name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "api.dbSecret" -}}
{{ .Values.name }}-db
{{- end }}
