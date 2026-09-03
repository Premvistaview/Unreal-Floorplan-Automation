// Copyright Epic Games, Inc. All Rights Reserved.

#include "SFloorPlanImportPanel.h"

#include "DesktopPlatformModule.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/PlatformApplicationMisc.h"
#include "IDesktopPlatform.h"
#include "IPythonScriptPlugin.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "Misc/ScopedSlowTask.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "PythonScriptTypes.h"
#include "Serialization/JsonWriter.h"
#include "Styling/AppStyle.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SNumericEntryBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SSeparator.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Views/STableRow.h"

#define LOCTEXT_NAMESPACE "SFloorPlanImportPanel"

namespace FloorPlanImportPanel
{
	const TCHAR* SettingsSection = TEXT("Floor2Dto3Dplan.ImportPanel");

	/** Keep the log bounded; a noisy DWG can emit thousands of lines. */
	constexpr int32 MaxLogLines = 4000;

	const TCHAR* FileDialogFilter =
		TEXT("Floor plans (*.png;*.jpg;*.jpeg;*.pdf;*.dwg;*.dxf)|*.png;*.jpg;*.jpeg;*.pdf;*.dwg;*.dxf|")
		TEXT("Images (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg|")
		TEXT("PDF (*.pdf)|*.pdf|")
		TEXT("CAD (*.dwg;*.dxf)|*.dwg;*.dxf|")
		TEXT("All files (*.*)|*.*");

	FSlateColor SeverityColor(const EFloorPlanLogSeverity Severity)
	{
		switch (Severity)
		{
		case EFloorPlanLogSeverity::Warning:
			return FSlateColor(FLinearColor(1.0f, 0.72f, 0.10f));
		case EFloorPlanLogSeverity::Error:
			return FSlateColor(FLinearColor(1.0f, 0.28f, 0.28f));
		case EFloorPlanLogSeverity::Success:
			return FSlateColor(FLinearColor(0.35f, 0.85f, 0.40f));
		default:
			return FSlateColor::UseForeground();
		}
	}

	EFloorPlanLogSeverity FromPythonLogType(const EPythonLogOutputType Type)
	{
		switch (Type)
		{
		case EPythonLogOutputType::Warning:
			return EFloorPlanLogSeverity::Warning;
		case EPythonLogOutputType::Error:
			return EFloorPlanLogSeverity::Error;
		default:
			return EFloorPlanLogSeverity::Info;
		}
	}

	/** Wraps a string as a single-quoted Python literal, escaping what Python would otherwise interpret. */
	FString ToPythonLiteral(const FString& Value)
	{
		FString Escaped = Value;
		Escaped.ReplaceInline(TEXT("\\"), TEXT("\\\\"), ESearchCase::CaseSensitive);
		Escaped.ReplaceInline(TEXT("'"), TEXT("\\'"), ESearchCase::CaseSensitive);
		Escaped.ReplaceInline(TEXT("\r"), TEXT(""), ESearchCase::CaseSensitive);
		Escaped.ReplaceInline(TEXT("\n"), TEXT("\\n"), ESearchCase::CaseSensitive);
		return FString::Printf(TEXT("'%s'"), *Escaped);
	}

	TSharedRef<SWidget> LabeledRow(const FText& Label, const FText& Tooltip, TSharedRef<SWidget> Content)
	{
		return SNew(SHorizontalBox)
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			[
				SNew(SBox)
				.WidthOverride(190.0f)
				[
					SNew(STextBlock)
					.Text(Label)
					.ToolTipText(Tooltip)
				]
			]
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			.VAlign(VAlign_Center)
			[
				Content
			];
	}

	TSharedRef<SWidget> SectionHeader(const FText& Label)
	{
		return SNew(STextBlock)
			.Text(Label)
			.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10));
	}
}

void SFloorPlanImportPanel::Construct(const FArguments& InArgs)
{
	LoadSettings();
	StatusText = LOCTEXT("StatusIdle", "Select a floor plan, then press Generate Walls.");

	ChildSlot
	[
		SNew(SBorder)
		.BorderImage(FAppStyle::Get().GetBrush("ToolPanel.GroupBorder"))
		.Padding(8.0f)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot()
			.AutoHeight()
			[
				BuildSourceSection()
			]
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 10.0f, 0.0f, 0.0f)
			[
				BuildSettingsSection()
			]
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 10.0f, 0.0f, 0.0f)
			[
				BuildActionSection()
			]
			+ SVerticalBox::Slot()
			.FillHeight(1.0f)
			.Padding(0.0f, 10.0f, 0.0f, 0.0f)
			[
				BuildLogSection()
			]
		]
	];

	AppendLog(
		TEXT("Panel ready. Final output is a Blueprint containing a saved Static Mesh; no Blender, FBX, or GLB is involved."),
		EFloorPlanLogSeverity::Info);
}

TSharedRef<SWidget> SFloorPlanImportPanel::BuildSourceSection()
{
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot()
		.AutoHeight()
		[
			FloorPlanImportPanel::SectionHeader(LOCTEXT("SourceHeader", "Source"))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 6.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("FileLabel", "Floor plan file"),
				LOCTEXT("FileTooltip", "PNG, JPG, JPEG, PDF, DWG, or DXF."),
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot()
				.FillWidth(1.0f)
				[
					SNew(SEditableTextBox)
					.Text_Lambda([this]() { return FText::FromString(FloorPlanPath); })
					.HintText(LOCTEXT("FileHint", "Browse to a PNG, JPG, PDF, DWG, or DXF floor plan"))
					.OnTextCommitted_Lambda([this](const FText& NewText, ETextCommit::Type)
					{
						FloorPlanPath = NewText.ToString().TrimStartAndEnd();
					})
				]
				+ SHorizontalBox::Slot()
				.AutoWidth()
				.Padding(6.0f, 0.0f, 0.0f, 0.0f)
				[
					SNew(SButton)
					.Text(LOCTEXT("Browse", "Browse..."))
					.OnClicked(this, &SFloorPlanImportPanel::OnBrowseClicked)
				])
		];
}

TSharedRef<SWidget> SFloorPlanImportPanel::BuildSettingsSection()
{
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot()
		.AutoHeight()
		[
			FloorPlanImportPanel::SectionHeader(LOCTEXT("SettingsHeader", "Detection and scale"))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 6.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("PixelsPerFootLabel", "Pixels per foot"),
				LOCTEXT("PixelsPerFootTooltip", "Raster scale: how many image pixels span one foot on the drawing. Used for PNG, JPG, and rasterised PDF."),
				SNew(SNumericEntryBox<float>)
				.AllowSpin(false)
				.MinValue(0.01f)
				.MinDesiredValueWidth(90.0f)
				.Value_Lambda([this]() { return TOptional<float>(PixelsPerFoot); })
				.OnValueChanged_Lambda([this](const float NewValue) { PixelsPerFoot = NewValue; }))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 4.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("WallHeightLabel", "Wall height (cm)"),
				LOCTEXT("WallHeightTooltip", "Extrusion height of every generated wall, in Unreal centimetres."),
				SNew(SNumericEntryBox<float>)
				.AllowSpin(false)
				.MinValue(1.0f)
				.MinDesiredValueWidth(90.0f)
				.Value_Lambda([this]() { return TOptional<float>(WallHeightCm); })
				.OnValueChanged_Lambda([this](const float NewValue) { WallHeightCm = NewValue; }))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 4.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("ThicknessLabel", "Fallback thickness (cm)"),
				LOCTEXT("ThicknessTooltip", "Thickness used when a wall's two faces cannot be paired up in the drawing."),
				SNew(SNumericEntryBox<float>)
				.AllowSpin(false)
				.MinValue(0.1f)
				.MinDesiredValueWidth(90.0f)
				.Value_Lambda([this]() { return TOptional<float>(DefaultThicknessCm); })
				.OnValueChanged_Lambda([this](const float NewValue) { DefaultThicknessCm = NewValue; }))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 4.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("DxfUnitsLabel", "DXF units to cm"),
				LOCTEXT("DxfUnitsTooltip", "Multiplier from drawing units to centimetres. Inches 2.54, millimetres 0.1, metres 100, already centimetres 1."),
				SNew(SNumericEntryBox<float>)
				.AllowSpin(false)
				.MinValue(0.0001f)
				.MinDesiredValueWidth(90.0f)
				.Value_Lambda([this]() { return TOptional<float>(DxfUnitsToCm); })
				.OnValueChanged_Lambda([this](const float NewValue) { DxfUnitsToCm = NewValue; }))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 4.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("PdfPageLabel", "PDF page index"),
				LOCTEXT("PdfPageTooltip", "Zero-based page to read from a PDF."),
				SNew(SNumericEntryBox<int32>)
				.AllowSpin(false)
				.MinValue(0)
				.MinDesiredValueWidth(90.0f)
				.Value_Lambda([this]() { return TOptional<int32>(PdfPageIndex); })
				.OnValueChanged_Lambda([this](const int32 NewValue) { PdfPageIndex = NewValue; }))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 4.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("RasterDpiLabel", "PDF raster DPI"),
				LOCTEXT("RasterDpiTooltip", "Resolution used when a PDF has no usable vector paths and must be rasterised."),
				SNew(SNumericEntryBox<float>)
				.AllowSpin(false)
				.MinValue(36.0f)
				.MinDesiredValueWidth(90.0f)
				.Value_Lambda([this]() { return TOptional<float>(RasterDpi); })
				.OnValueChanged_Lambda([this](const float NewValue) { RasterDpi = NewValue; }))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 4.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("LayerLabel", "CAD layer filter"),
				LOCTEXT("LayerTooltip", "Comma-separated DXF/DWG layer names. Leave empty to auto-pick layers whose name contains \"wall\", falling back to all layers."),
				SNew(SEditableTextBox)
				.Text_Lambda([this]() { return FText::FromString(CadLayerFilter); })
				.HintText(LOCTEXT("LayerHint", "Empty = auto-detect wall layers"))
				.OnTextCommitted_Lambda([this](const FText& NewText, ETextCommit::Type)
				{
					CadLayerFilter = NewText.ToString().TrimStartAndEnd();
				}))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 4.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("OdaLabel", "ODA File Converter"),
				LOCTEXT("OdaTooltip", "Path to ODAFileConverter.exe. Only needed for DWG input, which is converted to DXF first."),
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot()
				.FillWidth(1.0f)
				[
					SNew(SEditableTextBox)
					.Text_Lambda([this]() { return FText::FromString(OdaConverterPath); })
					.HintText(LOCTEXT("OdaHint", "Empty = search the default install locations"))
					.OnTextCommitted_Lambda([this](const FText& NewText, ETextCommit::Type)
					{
						OdaConverterPath = NewText.ToString().TrimStartAndEnd();
					})
				]
				+ SHorizontalBox::Slot()
				.AutoWidth()
				.Padding(6.0f, 0.0f, 0.0f, 0.0f)
				[
					SNew(SButton)
					.Text(LOCTEXT("BrowseOda", "Browse..."))
					.OnClicked(this, &SFloorPlanImportPanel::OnBrowseOdaClicked)
				])
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 6.0f, 0.0f, 0.0f)
		[
			FloorPlanImportPanel::LabeledRow(
				LOCTEXT("CollisionLabel", "Generate collision"),
				LOCTEXT("CollisionTooltip", "Use the generated triangles as complex-as-simple collision."),
				SNew(SCheckBox)
				.IsChecked_Lambda([this]()
				{
					return bGenerateCollision ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
				})
				.OnCheckStateChanged_Lambda([this](const ECheckBoxState NewState)
				{
					bGenerateCollision = (NewState == ECheckBoxState::Checked);
				}))
		];
}

TSharedRef<SWidget> SFloorPlanImportPanel::BuildActionSection()
{
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot()
		.AutoHeight()
		[
			SNew(SSeparator)
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 8.0f, 0.0f, 0.0f)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot()
			.AutoWidth()
			[
				SNew(SButton)
				.Text(LOCTEXT("Generate", "Generate Walls"))
				.ToolTipText(LOCTEXT("GenerateTooltip", "Detect walls, create a Static Mesh asset, and place a reusable Blueprint actor."))
				.IsEnabled_Lambda([this]() { return CanGenerate(); })
				.OnClicked(this, &SFloorPlanImportPanel::OnGenerateClicked)
			]
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			.VAlign(VAlign_Center)
			.Padding(12.0f, 0.0f, 0.0f, 0.0f)
			[
				SNew(STextBlock)
				.Text_Lambda([this]() { return StatusText; })
				.AutoWrapText(true)
			]
		];
}

TSharedRef<SWidget> SFloorPlanImportPanel::BuildLogSection()
{
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot()
		.AutoHeight()
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			.VAlign(VAlign_Center)
			[
				FloorPlanImportPanel::SectionHeader(LOCTEXT("LogHeader", "Log"))
			]
			+ SHorizontalBox::Slot()
			.AutoWidth()
			[
				SNew(SButton)
				.Text(LOCTEXT("CopyLog", "Copy"))
				.ToolTipText(LOCTEXT("CopyLogTooltip", "Copy the whole log to the clipboard."))
				.OnClicked(this, &SFloorPlanImportPanel::OnCopyLogClicked)
			]
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.Padding(6.0f, 0.0f, 0.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("ClearLog", "Clear"))
				.OnClicked(this, &SFloorPlanImportPanel::OnClearLogClicked)
			]
		]
		+ SVerticalBox::Slot()
		.FillHeight(1.0f)
		.Padding(0.0f, 6.0f, 0.0f, 0.0f)
		[
			SNew(SBorder)
			.BorderImage(FAppStyle::Get().GetBrush("Brushes.Recessed"))
			.Padding(4.0f)
			[
				SAssignNew(LogListView, SListView<TSharedPtr<FFloorPlanLogLine>>)
				.ListItemsSource(&LogLines)
				.SelectionMode(ESelectionMode::Multi)
				.OnGenerateRow(this, &SFloorPlanImportPanel::OnGenerateLogRow)
			]
		];
}

TSharedRef<ITableRow> SFloorPlanImportPanel::OnGenerateLogRow(
	TSharedPtr<FFloorPlanLogLine> Item,
	const TSharedRef<STableViewBase>& OwnerTable)
{
	return SNew(STableRow<TSharedPtr<FFloorPlanLogLine>>, OwnerTable)
		[
			SNew(STextBlock)
			.Text(FText::FromString(Item.IsValid() ? Item->Text : FString()))
			.ColorAndOpacity(FloorPlanImportPanel::SeverityColor(
				Item.IsValid() ? Item->Severity : EFloorPlanLogSeverity::Info))
			.Font(FCoreStyle::GetDefaultFontStyle("Mono", 9))
			.AutoWrapText(true)
		];
}

bool SFloorPlanImportPanel::CanGenerate() const
{
	return !bIsRunning && !FloorPlanPath.IsEmpty();
}

FReply SFloorPlanImportPanel::OnBrowseClicked()
{
	IDesktopPlatform* DesktopPlatform = FDesktopPlatformModule::Get();
	if (!DesktopPlatform)
	{
		AppendLog(TEXT("Desktop platform module is unavailable; cannot open a file dialog."), EFloorPlanLogSeverity::Error);
		return FReply::Handled();
	}

	const FString DefaultPath = FloorPlanPath.IsEmpty()
		? FPaths::ProjectDir()
		: FPaths::GetPath(FloorPlanPath);

	TArray<FString> OpenedFiles;
	const bool bOpened = DesktopPlatform->OpenFileDialog(
		FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
		LOCTEXT("SelectFloorPlan", "Select Floor Plan").ToString(),
		DefaultPath,
		FString(),
		FloorPlanImportPanel::FileDialogFilter,
		static_cast<uint32>(EFileDialogFlags::None),
		OpenedFiles);

	if (bOpened && OpenedFiles.Num() > 0)
	{
		FloorPlanPath = FPaths::ConvertRelativePathToFull(OpenedFiles[0]);
		SaveSettings();
		AppendLog(FString::Printf(TEXT("Selected %s"), *FloorPlanPath), EFloorPlanLogSeverity::Info);
		StatusText = LOCTEXT("StatusReady", "Ready. Press Generate Walls.");
	}

	return FReply::Handled();
}

FReply SFloorPlanImportPanel::OnBrowseOdaClicked()
{
	IDesktopPlatform* DesktopPlatform = FDesktopPlatformModule::Get();
	if (!DesktopPlatform)
	{
		return FReply::Handled();
	}

	TArray<FString> OpenedFiles;
	const bool bOpened = DesktopPlatform->OpenFileDialog(
		FSlateApplication::Get().FindBestParentWindowHandleForDialogs(nullptr),
		LOCTEXT("SelectOda", "Select ODAFileConverter.exe").ToString(),
		FString(),
		FString(),
		TEXT("Executable (*.exe)|*.exe|All files (*.*)|*.*"),
		static_cast<uint32>(EFileDialogFlags::None),
		OpenedFiles);

	if (bOpened && OpenedFiles.Num() > 0)
	{
		OdaConverterPath = FPaths::ConvertRelativePathToFull(OpenedFiles[0]);
		SaveSettings();
	}

	return FReply::Handled();
}

FReply SFloorPlanImportPanel::OnGenerateClicked()
{
	SaveSettings();
	RunImport();
	return FReply::Handled();
}

FReply SFloorPlanImportPanel::OnClearLogClicked()
{
	LogLines.Reset();
	if (LogListView.IsValid())
	{
		LogListView->RequestListRefresh();
	}
	return FReply::Handled();
}

FReply SFloorPlanImportPanel::OnCopyLogClicked()
{
	TArray<FString> Texts;
	Texts.Reserve(LogLines.Num());
	for (const TSharedPtr<FFloorPlanLogLine>& Line : LogLines)
	{
		if (Line.IsValid())
		{
			Texts.Add(Line->Text);
		}
	}

	FPlatformApplicationMisc::ClipboardCopy(*FString::Join(Texts, TEXT("\r\n")));
	return FReply::Handled();
}

void SFloorPlanImportPanel::AppendLog(const FString& Text, const EFloorPlanLogSeverity Severity)
{
	TArray<FString> Parts;
	Text.ParseIntoArrayLines(Parts, /*bCullEmpty*/ false);
	if (Parts.Num() == 0)
	{
		Parts.Add(FString());
	}

	for (FString& Part : Parts)
	{
		Part.RemoveFromEnd(TEXT("\r"), ESearchCase::CaseSensitive);
		LogLines.Add(MakeShared<FFloorPlanLogLine>(MoveTemp(Part), Severity));
	}

	if (LogLines.Num() > FloorPlanImportPanel::MaxLogLines)
	{
		LogLines.RemoveAt(0, LogLines.Num() - FloorPlanImportPanel::MaxLogLines, EAllowShrinking::No);
	}

	if (LogListView.IsValid())
	{
		LogListView->RequestListRefresh();
		if (LogLines.Num() > 0)
		{
			LogListView->RequestScrollIntoView(LogLines.Last());
		}
	}
}

FString SFloorPlanImportPanel::BuildOptionsJson() const
{
	FString Output;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Output);

	Writer->WriteObjectStart();
	Writer->WriteValue(TEXT("file_path"), FloorPlanPath);
	Writer->WriteValue(TEXT("pixels_per_foot"), PixelsPerFoot);
	Writer->WriteValue(TEXT("wall_height_cm"), WallHeightCm);
	Writer->WriteValue(TEXT("default_thickness_cm"), DefaultThicknessCm);
	Writer->WriteValue(TEXT("dxf_units_to_unreal_cm"), DxfUnitsToCm);
	Writer->WriteValue(TEXT("raster_dpi"), RasterDpi);
	Writer->WriteValue(TEXT("pdf_page_index"), PdfPageIndex);
	Writer->WriteValue(TEXT("cad_layer_filter"), CadLayerFilter);
	Writer->WriteValue(TEXT("oda_converter_path"), OdaConverterPath);
	Writer->WriteValue(TEXT("generate_collision"), bGenerateCollision);
	// The panel surfaces failures in its own log, so suppress the modal dialogs.
	Writer->WriteValue(TEXT("show_dialogs"), false);
	Writer->WriteObjectEnd();
	Writer->Close();

	return Output;
}

void SFloorPlanImportPanel::RunImport()
{
	IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
	if (!Python || !Python->IsPythonAvailable())
	{
		AppendLog(
			TEXT("Python is not available. Enable the Python Editor Script Plugin, then restart the editor."),
			EFloorPlanLogSeverity::Error);
		StatusText = LOCTEXT("StatusNoPython", "Failed: Python is not available.");
		return;
	}

	bIsRunning = true;
	ON_SCOPE_EXIT { bIsRunning = false; };

	AppendLog(TEXT("----------------------------------------"), EFloorPlanLogSeverity::Info);
	AppendLog(
		FString::Printf(TEXT("Generating walls from %s"), *FloorPlanPath),
		EFloorPlanLogSeverity::Info);

	FPythonCommandEx PythonCommand;
	PythonCommand.ExecutionMode = EPythonCommandExecutionMode::EvaluateStatement;
	PythonCommand.Command = FString::Printf(
		TEXT("__import__('floorplan_panel').run_from_json(%s)"),
		*FloorPlanImportPanel::ToPythonLiteral(BuildOptionsJson()));

	bool bCommandSucceeded = false;
	{
		FScopedSlowTask SlowTask(1.0f, LOCTEXT("Detecting", "Detecting walls and building meshes..."));
		SlowTask.MakeDialog();
		SlowTask.EnterProgressFrame(1.0f);

		bCommandSucceeded = Python->ExecPythonCommandEx(PythonCommand);
	}

	for (const FPythonLogOutputEntry& Entry : PythonCommand.LogOutput)
	{
		AppendLog(Entry.Output, FloorPlanImportPanel::FromPythonLogType(Entry.Type));
	}

	if (!bCommandSucceeded)
	{
		AppendLog(PythonCommand.CommandResult, EFloorPlanLogSeverity::Error);
		StatusText = LOCTEXT("StatusPythonError", "Failed: the Python pipeline raised an error. See the log.");
		return;
	}

	const int32 WallCount = FCString::Atoi(*PythonCommand.CommandResult);
	if (WallCount > 0)
	{
		AppendLog(
			FString::Printf(TEXT("Done. Generated %d wall segment(s)."), WallCount),
			EFloorPlanLogSeverity::Success);
		StatusText = FText::Format(
			LOCTEXT("StatusSuccess", "Generated {0} wall segment(s) as a Blueprint with a Static Mesh."),
			FText::AsNumber(WallCount));
	}
	else if (WallCount == 0)
	{
		StatusText = LOCTEXT("StatusNoWalls", "No walls were detected. Try adjusting the scale or layer filter.");
	}
	else
	{
		StatusText = LOCTEXT("StatusFailed", "Import failed. See the log for the reason.");
	}
}

void SFloorPlanImportPanel::LoadSettings()
{
	if (!GConfig)
	{
		return;
	}

	const TCHAR* Section = FloorPlanImportPanel::SettingsSection;
	GConfig->GetString(Section, TEXT("FloorPlanPath"), FloorPlanPath, GEditorPerProjectIni);
	GConfig->GetString(Section, TEXT("CadLayerFilter"), CadLayerFilter, GEditorPerProjectIni);
	GConfig->GetString(Section, TEXT("OdaConverterPath"), OdaConverterPath, GEditorPerProjectIni);
	GConfig->GetFloat(Section, TEXT("PixelsPerFoot"), PixelsPerFoot, GEditorPerProjectIni);
	GConfig->GetFloat(Section, TEXT("WallHeightCm"), WallHeightCm, GEditorPerProjectIni);
	GConfig->GetFloat(Section, TEXT("DefaultThicknessCm"), DefaultThicknessCm, GEditorPerProjectIni);
	GConfig->GetFloat(Section, TEXT("DxfUnitsToCm"), DxfUnitsToCm, GEditorPerProjectIni);
	GConfig->GetFloat(Section, TEXT("RasterDpi"), RasterDpi, GEditorPerProjectIni);
	GConfig->GetInt(Section, TEXT("PdfPageIndex"), PdfPageIndex, GEditorPerProjectIni);
	GConfig->GetBool(Section, TEXT("GenerateCollision"), bGenerateCollision, GEditorPerProjectIni);
}

void SFloorPlanImportPanel::SaveSettings() const
{
	if (!GConfig)
	{
		return;
	}

	const TCHAR* Section = FloorPlanImportPanel::SettingsSection;
	GConfig->SetString(Section, TEXT("FloorPlanPath"), *FloorPlanPath, GEditorPerProjectIni);
	GConfig->SetString(Section, TEXT("CadLayerFilter"), *CadLayerFilter, GEditorPerProjectIni);
	GConfig->SetString(Section, TEXT("OdaConverterPath"), *OdaConverterPath, GEditorPerProjectIni);
	GConfig->SetFloat(Section, TEXT("PixelsPerFoot"), PixelsPerFoot, GEditorPerProjectIni);
	GConfig->SetFloat(Section, TEXT("WallHeightCm"), WallHeightCm, GEditorPerProjectIni);
	GConfig->SetFloat(Section, TEXT("DefaultThicknessCm"), DefaultThicknessCm, GEditorPerProjectIni);
	GConfig->SetFloat(Section, TEXT("DxfUnitsToCm"), DxfUnitsToCm, GEditorPerProjectIni);
	GConfig->SetFloat(Section, TEXT("RasterDpi"), RasterDpi, GEditorPerProjectIni);
	GConfig->SetInt(Section, TEXT("PdfPageIndex"), PdfPageIndex, GEditorPerProjectIni);
	GConfig->SetBool(Section, TEXT("GenerateCollision"), bGenerateCollision, GEditorPerProjectIni);
	GConfig->Flush(false, GEditorPerProjectIni);
}

#undef LOCTEXT_NAMESPACE
