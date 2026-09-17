// Copyright Epic Games, Inc. All Rights Reserved.

#include "Floor2Dto3DplanEditorModule.h"

#include "Framework/Application/SlateApplication.h"
#include "Framework/Commands/UIAction.h"
#include "Framework/Docking/TabManager.h"
#include "Misc/ConfigCacheIni.h"
#include "Modules/ModuleManager.h"
#include "SFloorPlanImportPanel.h"
#include "SWallCorrectionPanel.h"
#include "Textures/SlateIcon.h"
#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"
#include "WorkspaceMenuStructure.h"
#include "WorkspaceMenuStructureModule.h"

#define LOCTEXT_NAMESPACE "Floor2Dto3DplanEditor"

IMPLEMENT_MODULE(FFloor2Dto3DplanEditorModule, Floor2Dto3DplanEditor)

const FName FFloor2Dto3DplanEditorModule::FloorPlanImportTabId(TEXT("FloorPlanImport"));
const FName FFloor2Dto3DplanEditorModule::WallCorrectionTabId(TEXT("FloorPlanWallCorrection"));
FWallCorrectionContext FFloor2Dto3DplanEditorModule::LastContext;
TWeakPtr<SWallCorrectionPanel> FFloor2Dto3DplanEditorModule::ActiveCorrectionPanel;

namespace
{
	const FName ToolMenuOwnerName(TEXT("Floor2Dto3DplanEditor"));
	const TCHAR* ContextSettingsSection = TEXT("Floor2Dto3Dplan.WallCorrection");
}

void FFloor2Dto3DplanEditorModule::OpenFloorPlanImportTab()
{
	FGlobalTabmanager::Get()->TryInvokeTab(FloorPlanImportTabId);
}

void FFloor2Dto3DplanEditorModule::OpenWallCorrection(const FWallCorrectionContext& Context)
{
	LastContext = Context;
	SaveLastContext();

	FGlobalTabmanager::Get()->TryInvokeTab(WallCorrectionTabId);
	if (const TSharedPtr<SWallCorrectionPanel> Panel = ActiveCorrectionPanel.Pin())
	{
		// The tab already existed, so its Construct did not run; push the new run in.
		Panel->SetContext(LastContext);
	}
}

void FFloor2Dto3DplanEditorModule::OpenWallCorrectionTab()
{
	FGlobalTabmanager::Get()->TryInvokeTab(WallCorrectionTabId);
}

void FFloor2Dto3DplanEditorModule::StartupModule()
{
	LoadLastContext();

	FGlobalTabmanager::Get()
		->RegisterNomadTabSpawner(
			FloorPlanImportTabId,
			FOnSpawnTab::CreateLambda([](const FSpawnTabArgs&) -> TSharedRef<SDockTab>
			{
				return SNew(SDockTab)
					.TabRole(ETabRole::NomadTab)
					[
						SNew(SFloorPlanImportPanel)
					];
			}))
		.SetDisplayName(LOCTEXT("FloorPlanImportTabTitle", "Floor Plan Import"))
		.SetTooltipText(LOCTEXT("FloorPlanImportTabTooltip", "Detect walls from a floor plan and stage them as one editable actor."))
		.SetGroup(WorkspaceMenu::GetMenuStructure().GetLevelEditorCategory());

	FGlobalTabmanager::Get()
		->RegisterNomadTabSpawner(
			WallCorrectionTabId,
			FOnSpawnTab::CreateLambda([](const FSpawnTabArgs&) -> TSharedRef<SDockTab>
			{
				TSharedRef<SWallCorrectionPanel> Panel = SNew(SWallCorrectionPanel);
				ActiveCorrectionPanel = Panel;
				Panel->SetContext(LastContext);
				return SNew(SDockTab)
					.TabRole(ETabRole::NomadTab)
					[
						Panel
					];
			}))
		.SetDisplayName(LOCTEXT("WallCorrectionTabTitle", "Wall Correction"))
		.SetTooltipText(LOCTEXT("WallCorrectionTabTooltip", "Review detected walls over the floor plan image: draw missed walls, remove false positives, then Finalize."))
		.SetGroup(WorkspaceMenu::GetMenuStructure().GetLevelEditorCategory());

	UToolMenus::RegisterStartupCallback(
		FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FFloor2Dto3DplanEditorModule::RegisterMenus));
}

void FFloor2Dto3DplanEditorModule::RegisterMenus()
{
	FToolMenuOwnerScoped OwnerScoped(ToolMenuOwnerName);

	UToolMenu* ToolsMenu = UToolMenus::Get()->ExtendMenu(TEXT("LevelEditor.MainMenu.Tools"));
	if (!ToolsMenu)
	{
		return;
	}

	FToolMenuSection& Section = ToolsMenu->FindOrAddSection(
		TEXT("FloorPlanToWalls"),
		LOCTEXT("FloorPlanSection", "Floor Plan"));

	Section.AddMenuEntry(
		TEXT("OpenFloorPlanImportPanel"),
		LOCTEXT("OpenFloorPlanImportPanel", "Floor Plan Import..."),
		LOCTEXT("OpenFloorPlanImportPanelTooltip", "Open the Floor Plan Import panel."),
		FSlateIcon(),
		FUIAction(FExecuteAction::CreateStatic(&FFloor2Dto3DplanEditorModule::OpenFloorPlanImportTab)));

	Section.AddMenuEntry(
		TEXT("OpenWallCorrectionWindow"),
		LOCTEXT("OpenWallCorrectionWindow", "Wall Correction..."),
		LOCTEXT("OpenWallCorrectionWindowTooltip", "Open the Wall Correction window for the last detected floor plan."),
		FSlateIcon(),
		FUIAction(FExecuteAction::CreateStatic(&FFloor2Dto3DplanEditorModule::OpenWallCorrectionTab)));
}

void FFloor2Dto3DplanEditorModule::ShutdownModule()
{
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(ToolMenuOwnerName);

	if (FSlateApplication::IsInitialized())
	{
		FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(FloorPlanImportTabId);
		FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(WallCorrectionTabId);
	}
}

void FFloor2Dto3DplanEditorModule::SaveLastContext()
{
	if (!GConfig)
	{
		return;
	}
	GConfig->SetString(ContextSettingsSection, TEXT("SourcePath"), *LastContext.SourcePath, GEditorPerProjectIni);
	GConfig->SetString(ContextSettingsSection, TEXT("TextureAssetPath"), *LastContext.TextureAssetPath, GEditorPerProjectIni);
	GConfig->SetFloat(ContextSettingsSection, TEXT("PixelsPerFoot"), LastContext.PixelsPerFoot, GEditorPerProjectIni);
	GConfig->SetFloat(ContextSettingsSection, TEXT("WallHeightCm"), LastContext.WallHeightCm, GEditorPerProjectIni);
	GConfig->SetFloat(ContextSettingsSection, TEXT("DefaultThicknessCm"), LastContext.DefaultThicknessCm, GEditorPerProjectIni);
	GConfig->SetBool(ContextSettingsSection, TEXT("GenerateCollision"), LastContext.bGenerateCollision, GEditorPerProjectIni);
	GConfig->SetBool(ContextSettingsSection, TEXT("CombinedActor"), LastContext.bCombinedActor, GEditorPerProjectIni);
	GConfig->Flush(false, GEditorPerProjectIni);
}

void FFloor2Dto3DplanEditorModule::LoadLastContext()
{
	if (!GConfig)
	{
		return;
	}
	GConfig->GetString(ContextSettingsSection, TEXT("SourcePath"), LastContext.SourcePath, GEditorPerProjectIni);
	GConfig->GetString(ContextSettingsSection, TEXT("TextureAssetPath"), LastContext.TextureAssetPath, GEditorPerProjectIni);
	GConfig->GetFloat(ContextSettingsSection, TEXT("PixelsPerFoot"), LastContext.PixelsPerFoot, GEditorPerProjectIni);
	GConfig->GetFloat(ContextSettingsSection, TEXT("WallHeightCm"), LastContext.WallHeightCm, GEditorPerProjectIni);
	GConfig->GetFloat(ContextSettingsSection, TEXT("DefaultThicknessCm"), LastContext.DefaultThicknessCm, GEditorPerProjectIni);
	GConfig->GetBool(ContextSettingsSection, TEXT("GenerateCollision"), LastContext.bGenerateCollision, GEditorPerProjectIni);
	GConfig->GetBool(ContextSettingsSection, TEXT("CombinedActor"), LastContext.bCombinedActor, GEditorPerProjectIni);
}

#undef LOCTEXT_NAMESPACE
