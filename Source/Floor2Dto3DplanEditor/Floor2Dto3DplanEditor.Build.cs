// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class Floor2Dto3DplanEditor : ModuleRules
{
	public Floor2Dto3DplanEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"Floor2Dto3Dplan"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			"ApplicationCore",
			"AssetTools",
			"DesktopPlatform",
			"GeometryCore",
			"GeometryFramework",
			"GeometryScriptingCore",
			"GeometryScriptingEditor",
			"InputCore",
			"Json",
			"PhysicsCore",
			"Projects",
			"PythonScriptPlugin",
			"Slate",
			"SlateCore",
			"ToolMenus",
			"UnrealEd",
			"WorkspaceMenuStructure"
		});
	}
}
