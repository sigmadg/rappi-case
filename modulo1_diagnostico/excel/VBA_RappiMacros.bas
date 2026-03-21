Attribute VB_Name = "RappiMacros"
' Módulo para alinear cálculos con modulo1_diagnostico/notebooks/01_diagnostico_operacional.ipynb
' Métrica: ratio = ORDERS / CONNECTED_RT (si CONNECTED_RT=0 -> ratio vacío/NaN en Excel)
' Clasificación: saturacion >1.8, sobre_oferta <0.5, saludable 0.9-1.2, resto intermedio
'
' Importar en Excel: Alt+F11 > Archivo > Importar archivo > este .bas
' Guardar libro como .xlsm (los .xlsx no guardan macros)

Option Explicit

Private Const SH_RAW As String = "RAW_DATA"
Private Const SH_RES As String = "RESUMEN_EXCEL"
Private Const SH_VAL As String = "VALIDACION"
Private Const SH_P1H As String = "P1_HORAS_SAT"

' --- Utilidad: localiza columna por encabezado (fila 1) ---
Private Function ColIndexByHeader(ws As Worksheet, header As String) As Long
    Dim c As Range
    Set c = ws.Rows(1).Find(What:=header, LookAt:=xlWhole, MatchCase:=False)
    If c Is Nothing Then
        ColIndexByHeader = 0
    Else
        ColIndexByHeader = c.Column
    End If
End Function

Private Function LastDataRow(ws As Worksheet) As Long
    LastDataRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
End Function

' Clasificación idéntica al notebook (clasificar)
Private Function ClasificarRatio(r As Variant) As String
    If IsEmpty(r) Or IsError(r) Then
        ClasificarRatio = vbNullString
        Exit Function
    End If
    If Not IsNumeric(r) Then
        ClasificarRatio = vbNullString
        Exit Function
    End If
    If r > 1.8 Then
        ClasificarRatio = "saturacion"
    ElseIf r < 0.5 Then
        ClasificarRatio = "sobre_oferta"
    ElseIf r >= 0.9 And r <= 1.2 Then
        ClasificarRatio = "saludable"
    Else
        ClasificarRatio = "intermedio"
    End If
End Function

' Asegura columnas RATIO y CLASIFICACION al final de RAW_DATA (cabeceras en fila 1)
Public Sub Rappi_AgregarColumnasMetricas()
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(SH_RAW)
    On Error GoTo 0
    If ws Is Nothing Then
        MsgBox "No existe la hoja '" & SH_RAW & "'.", vbExclamation
        Exit Sub
    End If

    Dim lc As Long
    lc = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
    If ColIndexByHeader(ws, "RATIO") = 0 Then
        ws.Cells(1, lc + 1).Value = "RATIO"
    End If
    If ColIndexByHeader(ws, "CLASIFICACION") = 0 Then
        lc = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column
        ws.Cells(1, lc + 1).Value = "CLASIFICACION"
    End If
    MsgBox "Columnas RATIO y CLASIFICACION listas (si faltaban). Ejecuta Rappi_CalcularRatio.", vbInformation
End Sub

' Calcula ratio y clasificación fila a fila (misma lógica que pandas)
Public Sub Rappi_CalcularRatio()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets(SH_RAW)

    Dim cOrd As Long, cConn As Long, cRat As Long, cCls As Long
    cOrd = ColIndexByHeader(ws, "ORDERS")
    cConn = ColIndexByHeader(ws, "CONNECTED_RT")
    cRat = ColIndexByHeader(ws, "RATIO")
    cCls = ColIndexByHeader(ws, "CLASIFICACION")

    If cOrd = 0 Or cConn = 0 Then
        MsgBox "Faltan columnas ORDERS o CONNECTED_RT.", vbExclamation
        Exit Sub
    End If
    If cRat = 0 Or cCls = 0 Then
        Rappi_AgregarColumnasMetricas
        cRat = ColIndexByHeader(ws, "RATIO")
        cCls = ColIndexByHeader(ws, "CLASIFICACION")
    End If

    Dim r As Long, lastR As Long
    lastR = LastDataRow(ws)
    If lastR < 2 Then Exit Sub

    Application.ScreenUpdating = False
    For r = 2 To lastR
        Dim conn As Variant, ord As Variant
        conn = ws.Cells(r, cConn).Value2
        ord = ws.Cells(r, cOrd).Value2

        If IsNumeric(conn) And conn <> 0 Then
            ws.Cells(r, cRat).Value = CDbl(ord) / CDbl(conn)
            ws.Cells(r, cCls).Value = ClasificarRatio(ws.Cells(r, cRat).Value)
        Else
            ws.Cells(r, cRat).ClearContents
            ws.Cells(r, cCls).ClearContents
        End If
    Next r
    Application.ScreenUpdating = True
    MsgBox "RATIO y CLASIFICACION calculados (" & (lastR - 1) & " filas).", vbInformation
End Sub

' Resumen principal alineado con prints del notebook (conteos saturación, %, medias)
Public Sub Rappi_GenerarResumen()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets(SH_RAW)

    Dim cCls As Long, cRat As Long, cEarn As Long, cDate As Long
    cCls = ColIndexByHeader(ws, "CLASIFICACION")
    cRat = ColIndexByHeader(ws, "RATIO")
    cEarn = ColIndexByHeader(ws, "EARNINGS")
    cDate = ColIndexByHeader(ws, "DATE")

    If cCls = 0 Or cRat = 0 Then
        MsgBox "Ejecuta primero Rappi_CalcularRatio.", vbExclamation
        Exit Sub
    End If

    Dim lastR As Long
    lastR = LastDataRow(ws)

    Dim n As Long, nSat As Long, nNa As Long
    Dim sumRat As Double, cntRat As Long
    Dim sumEarn As Double, cntEarn As Long
    Dim r As Long
    Dim v As Variant

    n = 0: nSat = 0: nNa = 0
    sumRat = 0: cntRat = 0
    sumEarn = 0: cntEarn = 0

    For r = 2 To lastR
        n = n + 1
        v = ws.Cells(r, cCls).Value
        If v = "saturacion" Then nSat = nSat + 1
        If IsEmpty(ws.Cells(r, cRat).Value) Or Not IsNumeric(ws.Cells(r, cRat).Value) Then
            nNa = nNa + 1
        Else
            sumRat = sumRat + CDbl(ws.Cells(r, cRat).Value)
            cntRat = cntRat + 1
        End If
        If cEarn > 0 Then
            If IsNumeric(ws.Cells(r, cEarn).Value) Then
                sumEarn = sumEarn + CDbl(ws.Cells(r, cEarn).Value)
                cntEarn = cntEarn + 1
            End If
        End If
    Next r

    Dim wsR As Worksheet
    Application.DisplayAlerts = False
    On Error Resume Next
    ThisWorkbook.Worksheets(SH_RES).Delete
    On Error GoTo 0
    Application.DisplayAlerts = True

    Set wsR = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
    wsR.Name = SH_RES

    wsR.Cells(1, 1).Value = "Métrica"
    wsR.Cells(1, 2).Value = "Valor Excel"
    wsR.Cells(2, 1).Value = "total_filas"
    wsR.Cells(2, 2).Value = n
    wsR.Cells(3, 1).Value = "filas_saturacion"
    wsR.Cells(3, 2).Value = nSat
    wsR.Cells(4, 1).Value = "pct_saturacion"
    wsR.Cells(4, 2).Value = IIf(n > 0, nSat / n, Empty)
    wsR.Cells(4, 2).NumberFormat = "0.00%"
    wsR.Cells(5, 1).Value = "ratio_mean (excluye NaN)"
    wsR.Cells(5, 2).Value = IIf(cntRat > 0, sumRat / cntRat, Empty)
    wsR.Cells(6, 1).Value = "filas_ratio_vacio"
    wsR.Cells(6, 2).Value = nNa
    wsR.Cells(7, 1).Value = "earnings_mean"
    wsR.Cells(7, 2).Value = IIf(cntEarn > 0, sumEarn / cntEarn, Empty)

    wsR.Columns("A:B").AutoFit
    MsgBox "Hoja '" & SH_RES & "' generada. Pega en VALIDACION columna C los valores del notebook y ejecuta Rappi_CompararConNotebook.", vbInformation
End Sub

' P1: conteo de filas saturadas por HORA (0-23), como p1h en el notebook
Public Sub Rappi_P1_HorasSaturacion()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets(SH_RAW)
    Dim cCls As Long, cHr As Long
    cCls = ColIndexByHeader(ws, "CLASIFICACION")
    cHr = ColIndexByHeader(ws, "HOUR")
    If cCls = 0 Or cHr = 0 Then
        MsgBox "Faltan CLASIFICACION o HOUR. Ejecuta Rappi_CalcularRatio.", vbExclamation
        Exit Sub
    End If

    Dim cnt(0 To 23) As Long
    Dim lastR As Long, r As Long
    lastR = LastDataRow(ws)

    For r = 2 To lastR
        If ws.Cells(r, cCls).Value = "saturacion" Then
            Dim h As Long
            If IsNumeric(ws.Cells(r, cHr).Value) Then
                h = CLng(ws.Cells(r, cHr).Value)
                If h >= 0 And h <= 23 Then cnt(h) = cnt(h) + 1
            End If
        End If
    Next r

    Dim wsP As Worksheet
    Application.DisplayAlerts = False
    On Error Resume Next
    ThisWorkbook.Worksheets(SH_P1H).Delete
    On Error GoTo 0
    Application.DisplayAlerts = True

    Set wsP = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
    wsP.Name = SH_P1H

    Dim i As Long
    wsP.Cells(1, 1).Value = "HOUR"
    wsP.Cells(1, 2).Value = "conteo_saturacion"
    For i = 0 To 23
        wsP.Cells(i + 2, 1).Value = i
        wsP.Cells(i + 2, 2).Value = cnt(i)
    Next i
    wsP.Columns("A:B").AutoFit
    MsgBox "Hoja '" & SH_P1H & "' creada (conteo por hora, saturación).", vbInformation
End Sub

' Agregación diaria: earn_mean, sat_frac, ratio_mean (mismo groupby DATE del notebook)
Public Sub Rappi_AgregacionDiaria()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets(SH_RAW)
    Dim cDate As Long, cCls As Long, cRat As Long, cEarn As Long
    cDate = ColIndexByHeader(ws, "DATE")
    cCls = ColIndexByHeader(ws, "CLASIFICACION")
    cRat = ColIndexByHeader(ws, "RATIO")
    cEarn = ColIndexByHeader(ws, "EARNINGS")
    If cDate = 0 Or cCls = 0 Or cRat = 0 Or cEarn = 0 Then
        MsgBox "Faltan DATE, CLASIFICACION, RATIO o EARNINGS.", vbExclamation
        Exit Sub
    End If

    Dim lastR As Long
    lastR = LastDataRow(ws)

    ' Diccionario simple: clave fecha serial, acumuladores
    Dim dict As Object
    Set dict = CreateObject("Scripting.Dictionary")

    Dim r As Long
    Dim dKey As Variant
    Dim k As Variant

    For r = 2 To lastR
        dKey = ws.Cells(r, cDate).Value2
        If IsEmpty(dKey) Then GoTo NextR

        If Not dict.Exists(dKey) Then
            dict.Add dKey, Array(0&, 0&, 0#, 0&, 0#) ' n, nSat, sumRat, cntRat, sumEarn
        End If
        Dim a() As Variant
        a = dict(dKey)
        a(0) = a(0) + 1
        If ws.Cells(r, cCls).Value = "saturacion" Then a(1) = a(1) + 1
        If IsNumeric(ws.Cells(r, cRat).Value) Then
            a(2) = a(2) + CDbl(ws.Cells(r, cRat).Value)
            a(3) = a(3) + 1
        End If
        If IsNumeric(ws.Cells(r, cEarn).Value) Then
            a(4) = a(4) + CDbl(ws.Cells(r, cEarn).Value)
        End If
        dict(dKey) = a
NextR:
    Next r

    Dim shName As String
    shName = "DAILY_AGG"
    Application.DisplayAlerts = False
    On Error Resume Next
    ThisWorkbook.Worksheets(shName).Delete
    On Error GoTo 0
    Application.DisplayAlerts = True

    Dim wsD As Worksheet
    Set wsD = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
    wsD.Name = shName

    wsD.Cells(1, 1).Value = "DATE"
    wsD.Cells(1, 2).Value = "earn_mean"
    wsD.Cells(1, 3).Value = "sat_frac"
    wsD.Cells(1, 4).Value = "ratio_mean"

    Dim rowOut As Long
    rowOut = 2
    Dim ks As Variant
    ks = dict.Keys
    Dim idx As Long
    For idx = LBound(ks) To UBound(ks)
        k = ks(idx)
        a = dict(k)
        wsD.Cells(rowOut, 1).Value = k
        wsD.Cells(rowOut, 1).NumberFormat = "yyyy-mm-dd"
        wsD.Cells(rowOut, 2).Value = IIf(a(0) > 0, a(4) / a(0), Empty)
        wsD.Cells(rowOut, 3).Value = IIf(a(0) > 0, a(1) / a(0), Empty)
        wsD.Cells(rowOut, 3).NumberFormat = "0.0000"
        wsD.Cells(rowOut, 4).Value = IIf(a(3) > 0, a(2) / a(3), Empty)
        rowOut = rowOut + 1
    Next idx

    wsD.Columns("A:D").AutoFit
    MsgBox "Hoja '" & shName & "' creada (agregación por DATE). Ordena por sat_frac para comparar con daily.head(10) del notebook.", vbInformation
End Sub

' Crea hoja VALIDACION con plantilla para pegar resultados del notebook (columna C)
Public Sub Rappi_CrearPlantillaValidacion()
    Dim wsV As Worksheet
    On Error Resume Next
    Set wsV = ThisWorkbook.Worksheets(SH_VAL)
    On Error GoTo 0

    If wsV Is Nothing Then
        Set wsV = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(1))
        wsV.Name = SH_VAL
    End If

    wsV.Cells.Clear
    wsV.Cells(1, 1).Value = "metric_key"
    wsV.Cells(1, 2).Value = "valor_excel"
    wsV.Cells(1, 3).Value = "valor_notebook_pegar"
    wsV.Cells(1, 4).Value = "diff_abs"
    wsV.Cells(1, 5).Value = "ok_tol"

    wsV.Cells(2, 1).Value = "total_filas"
    wsV.Cells(3, 1).Value = "filas_saturacion"
    wsV.Cells(4, 1).Value = "pct_saturacion"
    wsV.Cells(5, 1).Value = "ratio_mean"
    wsV.Cells(6, 1).Value = "filas_ratio_vacio"
    wsV.Cells(7, 1).Value = "earnings_mean"

    wsV.Columns("A:E").AutoFit
    MsgBox "Plantilla '" & SH_VAL & "' lista. Ejecuta Rappi_LlenarValidacionDesdeResumen después de RESUMEN_EXCEL.", vbInformation
End Sub

' Copia valores de RESUMEN_EXCEL a VALIDACION columna B
Public Sub Rappi_LlenarValidacionDesdeResumen()
    On Error GoTo ErrH
    Dim wsR As Worksheet, wsV As Worksheet
    Set wsR = ThisWorkbook.Worksheets(SH_RES)
    Set wsV = ThisWorkbook.Worksheets(SH_VAL)

    Dim r As Long
    For r = 2 To 7
        wsV.Cells(r, 2).Value = wsR.Cells(r, 2).Value
        If wsV.Cells(r, 1).Value = "pct_saturacion" Then
            wsV.Cells(r, 2).NumberFormat = "0.000000"
        End If
    Next r
    MsgBox "Columna B de VALIDACION actualizada desde RESUMEN_EXCEL.", vbInformation
    Exit Sub
ErrH:
    MsgBox "Ejecuta Rappi_GenerarResumen y Rappi_CrearPlantillaValidacion primero.", vbExclamation
End Sub

' Compara B vs C con tolerancia numérica (pct y medias)
Public Sub Rappi_CompararConNotebook()
    Dim wsV As Worksheet
    On Error Resume Next
    Set wsV = ThisWorkbook.Worksheets(SH_VAL)
    On Error GoTo 0
    If wsV Is Nothing Then
        MsgBox "No existe '" & SH_VAL & "'. Ejecuta Rappi_CrearPlantillaValidacion.", vbExclamation
        Exit Sub
    End If

    Const TOL As Double = 0.0001
    Dim r As Long
    For r = 2 To 7
        Dim ve As Variant, vn As Variant
        ve = wsV.Cells(r, 2).Value
        vn = wsV.Cells(r, 3).Value

        If IsEmpty(vn) Then
            wsV.Cells(r, 4).Value = "sin notebook"
            wsV.Cells(r, 5).Value = ""
            GoTo Cont
        End If

        If IsNumeric(ve) And IsNumeric(vn) Then
            wsV.Cells(r, 4).Value = Abs(CDbl(ve) - CDbl(vn))
            wsV.Cells(r, 5).Value = IIf(Abs(CDbl(ve) - CDbl(vn)) <= TOL Or Abs(CDbl(ve) - CDbl(vn)) <= TOL * (Abs(CDbl(vn)) + 1), "OK", "REVISAR")
        Else
            wsV.Cells(r, 4).Value = "n/a"
            wsV.Cells(r, 5).Value = ""
        End If
Cont:
    Next r
    MsgBox "Comparación lista (tolerancia " & TOL & "). Revisa columna ok_tol.", vbInformation
End Sub

' --- Ejecuta el flujo completo en orden ---
Public Sub Rappi_FlujoCompleto()
    Rappi_AgregarColumnasMetricas
    Rappi_CalcularRatio
    Rappi_GenerarResumen
    Rappi_P1_HorasSaturacion
    Rappi_AgregacionDiaria
    Rappi_CrearPlantillaValidacion
    Rappi_LlenarValidacionDesdeResumen
    MsgBox "Flujo completo. Pega en VALIDACION!C2:C7 los valores del notebook y ejecuta Rappi_CompararConNotebook.", vbInformation
End Sub
