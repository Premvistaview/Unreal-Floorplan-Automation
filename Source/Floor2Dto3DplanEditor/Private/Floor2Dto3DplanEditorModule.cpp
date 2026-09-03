// Copyright Epic Games, Inc. All Rights Reserved.

#include "Floor2Dto3DplanEditorModule.h"

#include "Framework/Application/SlateApplication.h"
#include "Framework/Commands/UIAction.h"
#include "Framework/Docking/TabManager.h"
#include "Modules/ModuleManager.h"
#include "SFloorPlanImportPanel.h"
#include "Textures/SlateIcon.h"
#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"
#include "WorkspaceMenuStructure.h"
#include "WorkspaceMenuStructureModule.h"

#define LOCTEXT_NAMESPACE "Floor2Dto3DplanEditor"

IMPLEMENT_MODULE(FFloor2Dto3DplanEditorModule, Floor2Dto3DplanEditor)

const FName FFloor2Dto3DplanEditorModule::FloorPlanImportTabId(TEXT("FloorPlanImport"));

namespace
{
	const FName ToolMenuOwnerName(TEXT("Floor2Dto3DplanEditor"));
}

void FFloor2Dto3DplanEditorModule::OpenFloorPlanImportTab()
{
	FGlobalTabmanager::Get()->TryInvokeTab(FloorPlanImportTabId);
}

void FFloor2Dto3DplanEditorModule::StartupModule()
{
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
		.SetTooltipText(LOCTEXT("FloorPlanImportTabTooltip", "Detect walls and create a Blueprint containing a saved Static Mesh."))
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
}

void FFloor2Dto3DplanEditorModule::ShutdownModule()
{
	UToolMenus::UnRegisterStartupCallback(this);
	UToolMenus::UnregisterOwner(ToolMenuOwnerName);

	if (FSlateApplication::IsInitialized())
	{
		FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(FloorPlanImportTabId);
	}
}

#undef LOCTEXT_NAMESPACE
